"""Planification et envoi des rappels d'étape.

    python -m scripts.rappels --planifier   # crée les rappels à venir
    python -m scripts.rappels --envoyer     # envoie ceux qui sont dus
    python -m scripts.rappels               # les deux

À faire tourner une fois par heure en tâche planifiée.

Deux garde-fous qui comptent
----------------------------
1. Le plafond WhatsApp. Tant que l'entreprise n'est pas vérifiée par Meta,
   le numéro est limité à 250 destinataires uniques par 24 h. Dépasser ne
   fait pas qu'échouer : cela dégrade la note de qualité du numéro et peut
   le faire restreindre. Le script s'arrête avant le plafond et bascule les
   rappels restants sur l'e-mail.

2. L'échec d'un canal ne doit pas perdre le rappel. Quand WhatsApp refuse,
   on retombe sur l'e-mail plutôt que d'abandonner : un étudiant qui rate
   une échéance parce que son numéro n'avait pas WhatsApp est un échec
   évitable.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.services import notifications as svc  # noqa: E402

# On prévient trois jours avant. Assez tôt pour réunir une pièce
# manquante, assez tard pour que le rappel reste actionnable.
JOURS_AVANT = 3

# Limites d'un compte d'essai Twilio. Ce ne sont pas des réglages mais des
# contraintes du fournisseur : une cinquantaine de messages par jour, un
# message toutes les trois secondes. On garde une marge sur le plafond, parce
# qu'un envoi refusé coûte un rejeu et salit les journaux.
PLAFOND_ESSAI_TWILIO = 45
CADENCE_ESSAI_TWILIO = 3.2


def planifier(db) -> int:
    """Crée les rappels pour les étapes à échéance, sans doublon.

    La contrainte d'unicité en base (utilisateur, canal, modèle, étape)
    fait le travail : relancer ce script ne crée jamais deux fois le même
    rappel.
    """
    lignes = db.execute(
        text(
            """
            SELECT r.utilisateur_id::text,
                   a.whatsapp_actif, a.telephone, a.email_actif, u.email,
                   r.contenu, r.etapes_faites
            FROM roadmap_enregistree r
            JOIN utilisateur u ON u.id = r.utilisateur_id
            LEFT JOIN abonnement_notification a ON a.utilisateur_id = r.utilisateur_id
            WHERE u.email_verifie = TRUE
            """
        )
    ).fetchall()

    crees = 0
    for uid, wa_actif, telephone, email_actif, email, contenu, faites in lignes:
        etapes = (contenu or {}).get("etapes") or []
        faites = set(faites or [])

        for index, etape in enumerate(etapes):
            if index in faites:
                continue
            echeance = etape.get("echeance")
            if not echeance:
                continue

            titre = etape.get("titre") or "Une étape de ton parcours"
            ordre = etape.get("ordre", index + 1)

            canaux = []
            if wa_actif and telephone:
                canaux.append(("whatsapp", telephone))
            if email_actif is not False and email:
                canaux.append(("email", email))

            for canal, _destinataire in canaux:
                resultat = db.execute(
                    text(
                        "INSERT INTO notification "
                        "  (utilisateur_id, canal, modele, parametres, etape_ordre, "
                        "   echeance, planifiee_pour) "
                        "VALUES (:u, CAST(:c AS canal_notification), 'rappel_etape', "
                        "        CAST(:p AS jsonb), :o, CAST(:e AS date), "
                        # CAST(...) plutôt que la syntaxe :e::date — les deux
                        # points de la conversion PostgreSQL seraient pris
                        # pour un second paramètre nommé.
                        "        CAST(CAST(:e AS date) - make_interval(days => :j) "
                        "             AS timestamptz)) "
                        "ON CONFLICT (utilisateur_id, canal, modele, etape_ordre) "
                        "DO NOTHING"
                    ),
                    {
                        "u": uid, "c": canal,
                        "p": json.dumps([titre, str(JOURS_AVANT)], ensure_ascii=False),
                        "o": ordre, "e": echeance, "j": JOURS_AVANT,
                    },
                )
                crees += resultat.rowcount or 0

    db.commit()
    return crees


def envoyer(db) -> tuple[int, int, int]:
    """Envoie les rappels dus. Renvoie (envoyés, repliés, échoués)."""
    # Le plafond dépend du fournisseur réellement actif, et ce sont ses
    # limites, pas les nôtres. Meta : 250 destinataires uniques par 24 h tant
    # que l'entreprise n'est pas vérifiée, on s'arrête à 240. Twilio en compte
    # d'essai : une cinquantaine de messages par jour, on s'arrête à 45.
    fournisseur = svc.fournisseur_whatsapp()
    plafond = (
        PLAFOND_ESSAI_TWILIO
        if fournisseur == "twilio" and settings.twilio_essai
        else settings.whatsapp_plafond_24h
    )

    deja = db.execute(text("SELECT destinataires FROM envois_whatsapp_24h")).scalar() or 0
    budget_whatsapp = max(plafond - deja, 0)
    if budget_whatsapp == 0:
        print(
            f"Plafond WhatsApp atteint ({deja} destinataires sur 24 h, "
            f"plafond {plafond} pour « {fournisseur} »). "
            "Les rappels partent par e-mail."
        )

    dus = db.execute(
        text(
            """
            SELECT n.id::text, n.canal::text, n.modele, n.parametres,
                   n.utilisateur_id::text, u.email, a.telephone
            FROM notification n
            JOIN utilisateur u ON u.id = n.utilisateur_id
            LEFT JOIN abonnement_notification a ON a.utilisateur_id = n.utilisateur_id
            WHERE n.statut = 'planifiee' AND n.planifiee_pour <= now()
            ORDER BY n.planifiee_pour
            LIMIT 500
            """
        )
    ).fetchall()

    envoyes = replis = echecs = 0

    for nid, canal, modele, parametres, _uid, email, telephone in dus:
        destinataire = telephone if canal == "whatsapp" else email

        if canal == "whatsapp" and budget_whatsapp <= 0:
            # Plutôt que d'échouer, on bascule ce rappel sur l'e-mail.
            canal, destinataire = "email", email
            replis += 1

        if not destinataire:
            _marquer(db, nid, "echouee", "aucun destinataire pour ce canal")
            echecs += 1
            continue

        try:
            svc.envoyer(svc.Envoi(canal, destinataire, modele, list(parametres)))
        except svc.ErreurNotification as e:
            # Repli vers l'e-mail si WhatsApp refuse — numéro sans compte
            # WhatsApp, template pas encore approuvé, etc.
            if canal == "whatsapp" and email:
                try:
                    svc.envoyer(svc.Envoi("email", email, modele, list(parametres)))
                    _marquer(db, nid, "envoyee", f"replié sur e-mail : {e}", canal="email")
                    replis += 1
                    continue
                except svc.ErreurNotification as e2:
                    e = e2
            _marquer(db, nid, "echouee", str(e))
            echecs += 1
            continue

        _marquer(db, nid, "envoyee", canal=canal)
        if canal == "whatsapp":
            budget_whatsapp -= 1
            # Un compte d'essai Twilio accepte un message toutes les trois
            # secondes. Envoyer plus vite ne fait pas gagner de temps : les
            # messages en excès reviennent en erreur 20429 et il faut les
            # rejouer. Autant respecter le rythme.
            if fournisseur == "twilio" and settings.twilio_essai:
                time.sleep(CADENCE_ESSAI_TWILIO)
        envoyes += 1

    db.commit()
    return envoyes, replis, echecs


def _marquer(db, nid: str, statut: str, motif: str | None = None, canal: str | None = None) -> None:
    db.execute(
        text(
            "UPDATE notification SET statut = CAST(:s AS statut_notification), "
            "  envoyee_le = CASE WHEN :s = 'envoyee' THEN now() ELSE envoyee_le END, "
            "  motif_echec = :m, tentatives = tentatives + 1, "
            "  canal = COALESCE(CAST(:c AS canal_notification), canal) "
            "WHERE id = :i"
        ),
        {"s": statut, "m": motif, "c": canal, "i": nid},
    )


def main() -> None:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--planifier", action="store_true")
    analyseur.add_argument("--envoyer", action="store_true")
    arguments = analyseur.parse_args()

    tout = not (arguments.planifier or arguments.envoyer)
    db = SessionLocal()

    if arguments.planifier or tout:
        print(f"{planifier(db)} rappel(s) planifié(s).")

    if arguments.envoyer or tout:
        envoyes, replis, echecs = envoyer(db)
        print(f"{envoyes} envoyé(s), {replis} replié(s) sur e-mail, {echecs} en échec.")

    db.close()


if __name__ == "__main__":
    main()
