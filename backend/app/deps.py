"""
deps.py — Dépendances FastAPI : session DB et utilisateur courant (JWT).
"""
from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session
from app.db import get_db
from app.security import decode_token
from app.models import User


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authentification requise")
    payload = decode_token(authorization.split(" ", 1)[1])
    if not payload:
        raise HTTPException(401, "Jeton invalide ou expiré")
    user = db.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(401, "Utilisateur introuvable")
    return user


def get_current_user_optional(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    payload = decode_token(authorization.split(" ", 1)[1])
    if not payload:
        return None
    return db.get(User, int(payload["sub"]))
