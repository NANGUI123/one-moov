"""
security.py — Hachage de mot de passe (bcrypt), politique de mot de passe,
jetons JWT et jetons à usage unique (vérification e-mail / reset).
"""
import re
import secrets
from datetime import datetime, timedelta, timezone
import bcrypt
from jose import jwt, JWTError
from app.config import get_settings

settings = get_settings()
ALGO = "HS256"


def valider_mot_de_passe(pw: str) -> str | None:
    """Retourne un message d'erreur si le mot de passe est trop faible, sinon None."""
    if len(pw or "") < 8:
        return "Le mot de passe doit contenir au moins 8 caractères."
    if not re.search(r"[A-Za-z]", pw):
        return "Le mot de passe doit contenir au moins une lettre."
    if not re.search(r"\d", pw):
        return "Le mot de passe doit contenir au moins un chiffre."
    return None


def nouveau_jeton() -> str:
    return secrets.token_urlsafe(32)


def _prep(password: str) -> bytes:
    # bcrypt ne gère que 72 octets max — on tronque proprement.
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prep(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prep(password), hashed.encode("utf-8"))
    except Exception:
        return False


def create_token(user_id: int, email: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "email": email, "exp": exp}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGO)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGO])
    except JWTError:
        return None
