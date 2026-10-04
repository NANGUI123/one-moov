"""
services/cinetpay.py — Intégration paiement CinetPay (mobile money Afrique).

Page de paiement hébergée + vérification serveur. En l'absence de clés
(CINETPAY_MODE=SANDBOX), on simule un checkout local pour pouvoir démontrer le
parcours sans compte marchand. Le vrai flux s'active dès que les clés sont là.
"""
import logging
import httpx
from app.config import get_settings
from app.services.urls import absolu

logger = logging.getLogger(__name__)
settings = get_settings()
API = "https://api-checkout.cinetpay.com/v2"

# Le Cameroun et le Congo-Brazzaville sont en zone CEMAC : leur franc CFA est
# le XAF, pas le XOF d'Afrique de l'Ouest. Les deux ont la même parité fixe
# avec l'euro (655,957), donc une erreur de code passe inaperçue tant qu'on
# reste en bac à sable — le montant reste juste. Elle ne passe pas au premier
# encaissement réel.
DEVISE = "XAF"


def is_live() -> bool:
    return bool(settings.CINETPAY_API_KEY and settings.CINETPAY_SITE_ID
                and settings.CINETPAY_MODE.upper() == "PRODUCTION")


def init_payment(transaction_id: str, amount_fcfa: int, description: str) -> dict:
    notify = absolu("/api/paiement/webhook")
    ret = absolu(f"/api/paiement/retour?tx={transaction_id}")
    if not is_live():
        # SANDBOX : page de paiement simulée servie par notre API. On construit
        # l'URL en ABSOLU pointant sur l'API, sinon le front sur Cloudflare
        # Pages sert son SPA fallback (index.html) et l'étudiant retombe sur
        # l'orientation au lieu d'arriver sur la page de simulation.
        return {"payment_url": absolu(f"/api/paiement/sandbox?tx={transaction_id}"),
                "transaction_id": transaction_id, "mode": "SANDBOX"}
    try:
        payload = {
            "apikey": settings.CINETPAY_API_KEY, "site_id": settings.CINETPAY_SITE_ID,
            "transaction_id": transaction_id, "amount": amount_fcfa,
            "currency": DEVISE,
            "description": description, "notify_url": notify, "return_url": ret,
            # ALL couvre le mobile money ET la carte bancaire. La carte sert
            # surtout au payeur de la diaspora : un parent ou un aîné en
            # France qui règle pour l'étudiant resté au pays.
            "channels": "ALL",
        }
        r = httpx.post(f"{API}/payment", json=payload, timeout=20)
        r.raise_for_status()
        data = r.json()
        return {"payment_url": data["data"]["payment_url"],
                "transaction_id": transaction_id, "mode": "PRODUCTION"}
    except Exception as e:
        logger.error(f"CinetPay init erreur : {e}")
        raise


def verify(transaction_id: str) -> str:
    """Retourne 'ACCEPTED' / 'REFUSED' / 'PENDING'."""
    if not is_live():
        return "ACCEPTED"  # sandbox
    try:
        payload = {"apikey": settings.CINETPAY_API_KEY, "site_id": settings.CINETPAY_SITE_ID,
                   "transaction_id": transaction_id}
        r = httpx.post(f"{API}/payment/check", json=payload, timeout=20)
        r.raise_for_status()
        return r.json().get("data", {}).get("status", "PENDING")
    except Exception as e:
        logger.error(f"CinetPay check erreur : {e}")
        return "PENDING"
