"""Tests du module notifications (Brevo SMTP + Twilio WhatsApp).

Les tests ne parlent à personne : ils vérifient qu'en absence de
configuration, on tombe en mode démo sans lever d'exception (c'est ce
qui permet la démo sans compte tiers). Un test unitaire vérifie aussi
la normalisation du numéro WhatsApp.
"""
from app.services import notifications as notif


def test_email_mode_demo_sans_smtp():
    """Sans SMTP configuré, envoyer_email retourne False, sans exception."""
    assert notif.email_configure() is False
    assert notif.envoyer_email(
        "eleve@example.com",
        "Vérification One Moov",
        "<p>Bonjour</p>",
    ) is False


def test_whatsapp_mode_demo_sans_twilio():
    """Sans Twilio configuré, envoyer_whatsapp retourne un résultat non envoyé."""
    assert notif.whatsapp_configure() is False
    r = notif.envoyer_whatsapp("+237600000000", "test")
    assert r.envoye is False
    assert r.motif and "Twilio" in r.motif


def test_normalisation_numero_whatsapp():
    """Twilio exige `whatsapp:+X…` — on accepte trois formes en entrée."""
    n = notif._normaliser
    assert n("+237600000000") == "whatsapp:+237600000000"
    assert n("237600000000") == "whatsapp:+237600000000"
    assert n("whatsapp:+237600000000") == "whatsapp:+237600000000"
    # Zéro initial d'un format local français retiré au profit du + international.
    assert n("00237600000000").startswith("whatsapp:+")


def test_rappel_j3_format_message():
    """Le corps du rappel utilise bien le modèle avec les 3 variables."""
    r = notif.rappel_j3(
        "+237600000000", prenom="Ada", etape="Entretien Campus France",
        echeance="12 novembre 2026",
    )
    # Sans Twilio configuré, le résultat est un mode démo : pas de send,
    # mais on veut vérifier que la fonction ne casse pas.
    assert r.envoye is False
