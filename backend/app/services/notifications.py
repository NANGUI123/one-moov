"""
services/notifications.py — E-mail (Brevo/SMTP) + WhatsApp (Twilio).

Un point d'entrée par canal, `envoyer_email()` et `envoyer_whatsapp()`.
Chaque canal choisit son fournisseur au démarrage selon la présence des
variables d'environnement. Sans elles, le message est écrit dans les
journaux — la démonstration fonctionne sans compte tiers.

**E-mail : Brevo par SMTP** (recommandé pour l'Afrique francophone)
    Brevo (ex-Sendinblue) délivre 300 e-mails/jour gratuits, avec des
    serveurs UE (conformité RGPD naturelle) et une bonne réputation
    d'envoi vers .cm et .cg.

    Configuration :
        SMTP_HOST=smtp-relay.brevo.com
        SMTP_PORT=587
        SMTP_USER=<login SMTP Brevo, format email>
        SMTP_PASSWORD=<clé SMTP Brevo>
        SMTP_FROM=One Moov <no-reply@onemoov.app>

**WhatsApp : Twilio WhatsApp Business API**
    Bac à sable actif en 5 min (l'étudiant envoie « join <code> » au
    numéro de test) puis production avec un numéro d'entreprise + templates.

    Configuration :
        TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
        TWILIO_AUTH_TOKEN=<jeton>
        TWILIO_WHATSAPP_FROM=whatsapp:+14155238886   # sandbox partagé

    En production, remplacer le numéro par celui de l'entreprise et
    faire approuver les templates de rappel (Meta Cloud API sous Twilio).
"""
from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ─────────────────────────────────────────────────────────────── e-mail

def email_configure() -> bool:
    """Vrai quand un SMTP est branché (Brevo ou autre)."""
    return bool(settings.SMTP_HOST)


def envoyer_email(destinataire: str, sujet: str, html: str, texte: str = "") -> bool:
    """Envoie un e-mail transactionnel. Retourne True en cas d'envoi réel.

    Sans SMTP configuré → mode démo : log seulement, l'appelant peut
    afficher le lien de vérification à l'écran.
    """
    if not email_configure():
        logger.info("[mode démo e-mail] pas de SMTP — %s / « %s »", destinataire, sujet)
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = sujet
        msg["From"] = settings.SMTP_FROM
        msg["To"] = destinataire
        msg.set_content(texte or "Ouvrez cet e-mail dans un client HTML.")
        msg.add_alternative(html, subtype="html")
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as s:
            if settings.SMTP_TLS:
                s.starttls()
            if settings.SMTP_USER:
                s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("Envoi e-mail échoué : %s", e)
        return False


# ────────────────────────────────────────────────────────── WhatsApp


@dataclass
class ResultatWhatsApp:
    """Ce que l'appelant peut vouloir savoir : envoyé, id fournisseur, motif."""
    envoye: bool
    identifiant: Optional[str] = None
    motif: Optional[str] = None


def whatsapp_configure() -> bool:
    """Vrai quand un fournisseur WhatsApp est branché (Twilio pour l'instant)."""
    return bool(
        getattr(settings, "TWILIO_ACCOUNT_SID", "")
        and getattr(settings, "TWILIO_AUTH_TOKEN", "")
        and getattr(settings, "TWILIO_WHATSAPP_FROM", "")
    )


def _normaliser(numero: str) -> str:
    """Retourne un numéro au format `whatsapp:+XXXXXXXX`.

    Twilio exige ce préfixe. On accepte les entrées « +237... » ou
    « 237... » ou « whatsapp:+237... » indifféremment.
    """
    n = (numero or "").strip().replace(" ", "")
    if n.startswith("whatsapp:"):
        return n
    if not n.startswith("+"):
        n = "+" + n.lstrip("0")
    return f"whatsapp:{n}"


def envoyer_whatsapp(
    destinataire: str,
    corps: str,
    *,
    template_sid: Optional[str] = None,
    variables: Optional[dict[str, str]] = None,
) -> ResultatWhatsApp:
    """Envoie un WhatsApp via Twilio.

    Deux formes :
      - `corps` seul : message libre, ne fonctionne que dans les 24 h qui
        suivent un message entrant de l'étudiant (fenêtre Meta).
      - `template_sid` : template approuvé par Meta, fonctionne hors fenêtre.
        Les rappels J-3 des étapes critiques passent par là.

    Sans configuration Twilio → mode démo : log seulement, l'appelant
    continue son cours normalement (utile en dev et pour la démo).
    """
    if not whatsapp_configure():
        logger.info(
            "[mode démo WhatsApp] pas de compte Twilio — %s / %s caractères",
            destinataire, len(corps or ""),
        )
        return ResultatWhatsApp(envoye=False, motif="Configuration Twilio absente")

    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    )
    donnees: dict[str, str] = {
        "From": settings.TWILIO_WHATSAPP_FROM,
        "To": _normaliser(destinataire),
    }
    if template_sid:
        donnees["ContentSid"] = template_sid
        if variables:
            import json as _json
            donnees["ContentVariables"] = _json.dumps(variables, ensure_ascii=False)
    else:
        donnees["Body"] = corps or ""

    try:
        r = httpx.post(
            url,
            data=donnees,
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            timeout=15.0,
        )
        if r.status_code >= 400:
            logger.warning("Twilio a refusé (%s) : %s", r.status_code, r.text[:200])
            return ResultatWhatsApp(envoye=False, motif=f"HTTP {r.status_code}")
        sid = ""
        try:
            sid = r.json().get("sid", "")
        except ValueError:
            pass
        return ResultatWhatsApp(envoye=True, identifiant=sid)
    except httpx.RequestError as e:
        logger.error("Twilio inaccessible : %s", e)
        return ResultatWhatsApp(envoye=False, motif=str(e))


# ─────────────────────────────────────────────── rappels d'étapes critiques

MODELE_RAPPEL_J3 = (
    "Bonjour {prenom}, ici One Moov. Il te reste 3 jours pour boucler « {etape} » "
    "(échéance {echeance}). Ouvre l'app pour marquer l'étape faite ou nous dire "
    "où tu en es. Ton parcours France reste à jour."
)


def rappel_j3(destinataire: str, prenom: str, etape: str, echeance: str) -> ResultatWhatsApp:
    """Envoi typé du rappel J-3 sur une étape critique.

    En sandbox / hors template : envoi libre (fonctionne dans les 24 h qui
    suivent un message entrant). En production, remplacer par un template
    Meta approuvé et passer le SID via ``TWILIO_RAPPEL_TEMPLATE_SID``.
    """
    template_sid = getattr(settings, "TWILIO_RAPPEL_TEMPLATE_SID", "") or None
    if template_sid:
        return envoyer_whatsapp(
            destinataire,
            corps="",
            template_sid=template_sid,
            variables={"1": prenom, "2": etape, "3": echeance},
        )
    return envoyer_whatsapp(
        destinataire,
        corps=MODELE_RAPPEL_J3.format(prenom=prenom, etape=etape, echeance=echeance),
    )
