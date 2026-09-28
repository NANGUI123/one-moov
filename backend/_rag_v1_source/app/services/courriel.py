"""Envoi des codes de vérification.

Sans SMTP configuré, le code est écrit dans les journaux du serveur au lieu
d'être envoyé. C'est utilisable en développement et en démonstration, et
c'est explicitement signalé à chaque envoi — parce qu'un code de
vérification dans des journaux consultables n'a plus rien d'un secret.

Le message ne contient pas de lien cliquable : un code à recopier résiste
mieux à l'hameçonnage, et évite d'avoir à faire correspondre une URL de
retour avec l'environnement de déploiement.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


def smtp_configure() -> bool:
    return bool(settings.smtp_hote and settings.smtp_utilisateur)


def envoyer_code(destinataire: str, code: str) -> bool:
    """Envoie le code. Renvoie False si l'envoi n'a pas eu lieu."""
    if not smtp_configure():
        logger.warning(
            "SMTP non configuré : le code de vérification de %s est %s. "
            "À ne jamais laisser en production.",
            destinataire, code,
        )
        return False

    message = EmailMessage()
    message["Subject"] = "Ton code de vérification One Moov"
    message["From"] = settings.smtp_expediteur
    message["To"] = destinataire
    message.set_content(
        f"Bonjour,\n\n"
        f"Ton code de vérification One Moov est : {code}\n\n"
        f"Il est valable {settings.verification_duree_minutes} minutes.\n\n"
        f"Si tu n'as pas créé de compte One Moov, ignore ce message : "
        f"aucun compte ne sera activé sans ce code.\n\n"
        f"L'équipe One Moov"
    )

    try:
        with smtplib.SMTP(settings.smtp_hote, settings.smtp_port, timeout=15) as serveur:
            serveur.starttls()
            serveur.login(settings.smtp_utilisateur, settings.smtp_motdepasse)
            serveur.send_message(message)
    except (smtplib.SMTPException, OSError) as e:
        # On ne propage pas : l'inscription ne doit pas échouer parce que le
        # serveur de messagerie a hoqueté. L'étudiant peut redemander un code.
        logger.error("Envoi du code à %s impossible : %s", destinataire, e)
        return False

    return True
