"""
services/urls.py — Construction robuste d'URL publiques.

Un seul endroit qui sait fabriquer une URL absolue vers l'API à partir de
PUBLIC_BASE_URL, quelle que soit la forme sous laquelle Render la fournit
(URL complète, hostname bare, hostname:port interne). Les liens envoyés
aux étudiants (vérification e-mail, page de paiement sandbox, webhooks)
en dépendent — leur cassure laisse l'étudiant devant une page « site
inaccessible ».
"""
from app.config import get_settings


def base_publique() -> str:
    """Renvoie l'URL absolue publique de l'API, sans slash final.

    Trois cas gérés :
      - vide → `http://localhost:8000` (développement) ;
      - URL déjà complète (`http://...` ou `https://...`) → renvoyée
        telle quelle, sans le slash final ;
      - hostname sans schéma (`one-moov-api` ou `one-moov-api:10000`) →
        interprété comme un service Render interne : on retire le port,
        on ajoute `.onrender.com` si le domaine n'a pas de point, et on
        préfixe `https://`.
    """
    b = (get_settings().PUBLIC_BASE_URL or "").strip().rstrip("/")
    if not b:
        return "http://localhost:8000"
    if b.startswith(("http://", "https://")):
        return b
    hote = b.split(":", 1)[0]
    if "." not in hote:
        hote = f"{hote}.onrender.com"
    return f"https://{hote}"


def absolu(chemin: str) -> str:
    """Retourne l'URL absolue d'un chemin d'API (`/api/...`)."""
    if not chemin.startswith("/"):
        chemin = "/" + chemin
    return f"{base_publique()}{chemin}"
