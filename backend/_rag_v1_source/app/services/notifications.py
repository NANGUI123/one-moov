"""Notifications : WhatsApp et e-mail.

Deux chemins vers WhatsApp, et ils ne servent pas le même moment
---------------------------------------------------------------
    twilio   Le bac à sable s'active en cinq minutes. L'étudiant envoie
             « join <code> » au numéro de test et devient joignable. Dans les
             24 heures qui suivent un message entrant, le texte est libre :
             aucun template à faire approuver. C'est le seul moyen de montrer
             la chaîne complète tout de suite.

    meta     L'API Cloud officielle, la cible en production. Un numéro
             d'entreprise, des templates approuvés, et surtout la possibilité
             d'écrire HORS de la fenêtre de 24 heures — ce dont un rappel
             d'échéance a besoin par définition.

La même fonction envoyer() sert les deux. Passer du bac à sable à la
production change une variable d'environnement, pas du code.

Ce que WhatsApp impose, et qui dicte toute la conception
--------------------------------------------------------
Un rappel du type « ton dossier ferme dans 3 jours » part par définition
hors de la fenêtre de 24 heures qui suit un message de l'étudiant. Meta
exige donc un *template* préalablement approuvé, de catégorie « utility ».
On ne peut pas composer le texte librement : on nomme un template et on
fournit ses paramètres positionnels.

D'où le fait que le nom du template et ses paramètres soient en base plutôt
que construits dans le code : un template rejeté, renommé ou re-catégorisé
par Meta se corrige alors sans redéploiement.

Chaque modèle porte donc trois rendus du même message : les paramètres du
template Meta, un texte libre pour Twilio, et un e-mail. Trois formes, une
seule information — sinon les canaux finissent par ne plus dire la même
chose, et c'est le genre d'écart qu'on découvre par une réclamation.

Le plafond de 250
-----------------
Tant que l'entreprise n'est pas vérifiée par Meta, le numéro est limité à
250 destinataires uniques par 24 heures. Dépasser ne fait pas qu'échouer :
cela dégrade la note de qualité du numéro et peut le faire restreindre. Le
planificateur s'arrête donc avant le plafond, plutôt que de laisser l'API
refuser.

L'e-mail n'est pas un second choix
-----------------------------------
Il n'a aucun plafond, aucun template à faire approuver, et il touche les
étudiants qui ne donnent pas leur numéro. Il sert de canal de repli
systématique quand WhatsApp échoue ou n'est pas configuré.
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import httpx

from app.config import settings
from app.services.metriques import compteurs

logger = logging.getLogger(__name__)


class ErreurNotification(Exception):
    """L'envoi n'a pas pu aboutir."""


# --- Les modèles de message ---------------------------------------------
#
# La clé est le nom du template tel qu'il est déclaré chez Meta. Le rendu
# e-mail reprend les mêmes paramètres, dans le même ordre, pour que les deux
# canaux disent exactement la même chose.

MODELES: dict[str, dict] = {
    "rappel_etape": {
        "langue": "fr",
        "parametres": ["titre de l'étape", "nombre de jours"],
        # Texte libre, utilisé par Twilio dans la fenêtre de 24 h. Court : il
        # est lu sur un écran de téléphone, souvent en notification.
        "whatsapp_texte": (
            "One Moov — {0} dans {1} jours.\n"
            "Ouvre l'application pour voir les pièces à préparer."
        ),
        "email_sujet": "One Moov — {0} dans {1} jours",
        "email_corps": (
            "Bonjour,\n\n"
            "Une étape de ton parcours approche : {0}.\n"
            "Il te reste {1} jours.\n\n"
            "Ouvre One Moov pour voir le détail et les pièces à préparer.\n\n"
            "Pour ne plus recevoir ces rappels, désactive-les dans l'onglet "
            "Alertes de l'application."
        ),
    },
    "valeur_a_reverifier": {
        "langue": "fr",
        "parametres": ["libellé de la valeur", "nom de la source"],
        "whatsapp_texte": (
            "One Moov — une information de ta feuille de route est à "
            "confirmer : {0}.\nVérifie-la sur {1} avant toute démarche."
        ),
        "email_sujet": "One Moov — une information à confirmer",
        "email_corps": (
            "Bonjour,\n\n"
            "Une information de ta feuille de route n'a pas été vérifiée "
            "récemment : {0}.\n"
            "Confirme-la sur {1} avant toute démarche.\n\n"
            "L'équipe One Moov"
        ),
    },
}


@dataclass
class Envoi:
    canal: str            # whatsapp | email
    destinataire: str     # numéro international, ou adresse e-mail
    modele: str
    parametres: list[str]


# =========================================================================
# WhatsApp, via Twilio
# =========================================================================


def twilio_configure() -> bool:
    return bool(settings.twilio_account_sid and settings.twilio_auth_token)


# Les codes d'erreur qu'on rencontre réellement, traduits une fois pour
# toutes. On les relira dans les journaux à deux heures du matin, et
# « HTTP 400 » ne dira rien à ce moment-là.
_ERREURS_TWILIO = {
    "63016": (
        "message libre envoyé hors de la fenêtre de 24 h : il faut un template "
        "approuvé, donc passer sur Meta ou déclarer un Content Template chez Twilio"
    ),
    "63015": "le destinataire n'a pas de compte WhatsApp joignable",
    "63003": "destinataire introuvable sur le canal WhatsApp",
    "63007": "le numéro expéditeur n'est pas un expéditeur WhatsApp valide",
    "21608": (
        "compte d'essai : le destinataire doit d'abord envoyer « join <code> » "
        "au numéro du bac à sable"
    ),
    "21610": "le destinataire s'est désabonné de ce numéro",
    "20429": "trop de messages d'affilée : un compte d'essai accepte un envoi toutes les 3 s",
}


def _envoyer_twilio(envoi: Envoi) -> None:
    if not twilio_configure():
        raise ErreurNotification("Twilio n'est pas configuré.")

    modele = MODELES.get(envoi.modele)
    if not modele:
        raise ErreurNotification(f"Modèle inconnu : {envoi.modele}")

    texte = modele["whatsapp_texte"].format(*envoi.parametres)

    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.twilio_account_sid}/Messages.json"
    )
    # Le préfixe « whatsapp: » est ce qui distingue le canal du SMS. Sans lui,
    # Twilio enverrait un SMS, qui est payant et que l'étudiant ne recevrait
    # probablement pas.
    donnees = {
        "From": f"whatsapp:{settings.twilio_numero}",
        "To": f"whatsapp:{envoi.destinataire}",
        "Body": texte,
    }

    try:
        with httpx.Client(timeout=30) as client:
            reponse = client.post(
                url,
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                data=donnees,
            )
    except httpx.RequestError as e:
        raise ErreurNotification(f"Twilio injoignable : {e}") from e

    if reponse.status_code >= 400:
        brut = reponse.text[:400]
        for code, explication in _ERREURS_TWILIO.items():
            if code in brut:
                raise ErreurNotification(f"Twilio a refusé l'envoi : {explication}")
        raise ErreurNotification(f"Twilio a refusé l'envoi : {brut}")


# =========================================================================
# WhatsApp, via l'API Cloud de Meta
# =========================================================================


def whatsapp_configure() -> bool:
    return bool(settings.whatsapp_token and settings.whatsapp_numero_id)


def _envoyer_whatsapp(envoi: Envoi) -> None:
    if not whatsapp_configure():
        raise ErreurNotification("WhatsApp n'est pas configuré.")

    modele = MODELES.get(envoi.modele)
    if not modele:
        raise ErreurNotification(f"Modèle inconnu : {envoi.modele}")

    url = (
        f"https://graph.facebook.com/{settings.whatsapp_version_api}"
        f"/{settings.whatsapp_numero_id}/messages"
    )
    charge = {
        "messaging_product": "whatsapp",
        "to": envoi.destinataire.lstrip("+"),
        "type": "template",
        "template": {
            "name": envoi.modele,
            "language": {"code": modele["langue"]},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": str(p)} for p in envoi.parametres
                    ],
                }
            ],
        },
    }

    try:
        with httpx.Client(timeout=30) as client:
            reponse = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.whatsapp_token}",
                    "Content-Type": "application/json",
                },
                json=charge,
            )
    except httpx.RequestError as e:
        raise ErreurNotification(f"WhatsApp injoignable : {e}") from e

    if reponse.status_code >= 400:
        # Les erreurs les plus fréquentes méritent un message clair : on les
        # relira dans les journaux à 2 h du matin.
        detail = reponse.text[:300]
        if "131026" in detail:
            detail = "le destinataire n'a pas de compte WhatsApp actif"
        elif "132001" in detail:
            detail = "le template n'existe pas ou n'est pas encore approuvé"
        elif "131047" in detail:
            detail = "hors fenêtre de 24 h : un template approuvé est obligatoire"
        raise ErreurNotification(f"WhatsApp a refusé l'envoi : {detail}")


# =========================================================================
# E-mail
# =========================================================================


def email_configure() -> bool:
    return bool(settings.smtp_hote and settings.smtp_utilisateur)


def _envoyer_email(envoi: Envoi) -> None:
    modele = MODELES.get(envoi.modele)
    if not modele:
        raise ErreurNotification(f"Modèle inconnu : {envoi.modele}")

    sujet = modele["email_sujet"].format(*envoi.parametres)
    corps = modele["email_corps"].format(*envoi.parametres)

    if not email_configure():
        logger.warning(
            "SMTP non configuré : e-mail non envoyé à %s — %s",
            envoi.destinataire, sujet,
        )
        raise ErreurNotification("SMTP n'est pas configuré.")

    message = EmailMessage()
    message["Subject"] = sujet
    message["From"] = settings.smtp_expediteur
    message["To"] = envoi.destinataire
    message.set_content(corps)

    try:
        with smtplib.SMTP(settings.smtp_hote, settings.smtp_port, timeout=20) as serveur:
            serveur.starttls()
            serveur.login(settings.smtp_utilisateur, settings.smtp_motdepasse)
            serveur.send_message(message)
    except (smtplib.SMTPException, OSError) as e:
        raise ErreurNotification(f"Envoi e-mail impossible : {e}") from e


# =========================================================================
# Aiguillage
# =========================================================================


def fournisseur_whatsapp() -> str:
    """Le fournisseur WhatsApp réellement utilisable, ou « mock ».

    Un fournisseur nommé mais sans clé retombe en mock plutôt que d'échouer à
    chaque envoi : on préfère un journal explicite à une file de rappels qui
    se vide en erreurs.
    """
    if settings.notifications_mock:
        return "mock"

    choix = (settings.notifications_fournisseur or "mock").lower()
    if choix == "twilio" and twilio_configure():
        return "twilio"
    if choix == "meta" and whatsapp_configure():
        return "meta"
    return "mock"


def envoyer(envoi: Envoi) -> None:
    """Envoie sur le canal demandé. Lève ErreurNotification en cas d'échec."""
    fournisseur = fournisseur_whatsapp() if envoi.canal == "whatsapp" else None

    if settings.notifications_mock or fournisseur == "mock":
        logger.info(
            "[mock] %s vers %s : %s %s",
            envoi.canal, envoi.destinataire, envoi.modele, envoi.parametres,
        )
        compteurs.incrementer(f"notification.mock.{envoi.canal}")
        return

    if envoi.canal == "whatsapp":
        if fournisseur == "twilio":
            _envoyer_twilio(envoi)
        else:
            _envoyer_whatsapp(envoi)
        compteurs.incrementer(f"notification.envoyee.whatsapp.{fournisseur}")
        return

    if envoi.canal == "email":
        _envoyer_email(envoi)
        compteurs.incrementer("notification.envoyee.email")
        return

    raise ErreurNotification(f"Canal inconnu : {envoi.canal}")


def info() -> dict:
    return {
        "mock": settings.notifications_mock,
        "fournisseur_whatsapp": fournisseur_whatsapp(),
        "whatsapp": {
            # « configure » reste le nom historique : au moins un chemin
            # WhatsApp est utilisable.
            "configure": twilio_configure() or whatsapp_configure(),
            "twilio": {
                "configure": twilio_configure(),
                "compte_essai": settings.twilio_essai,
                "numero": settings.twilio_numero,
            },
            "meta": {
                "configure": whatsapp_configure(),
                "plafond_24h": settings.whatsapp_plafond_24h,
            },
            "modeles": sorted(MODELES),
        },
        "email": {"configure": email_configure()},
    }
