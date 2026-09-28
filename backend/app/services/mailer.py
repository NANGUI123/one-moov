"""
services/mailer.py — Envoi d'e-mails (vérification, réinitialisation).

Si SMTP_HOST est configuré → envoi réel (TLS). Sinon → mode démo : rien n'est envoyé,
l'appelant affiche le lien à l'écran pour permettre les tests sans compte e-mail.
"""
import logging
import smtplib
from email.message import EmailMessage
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def configure() -> bool:
    return bool(settings.SMTP_HOST)


def envoyer(destinataire: str, sujet: str, html: str, texte: str = "") -> bool:
    """Retourne True si l'e-mail a été envoyé, False si mode démo / échec."""
    if not configure():
        logger.info(f"[mode démo e-mail] pas de SMTP — e-mail à {destinataire} non envoyé")
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
    except Exception as e:
        logger.error(f"Envoi e-mail échoué ({e})")
        return False
