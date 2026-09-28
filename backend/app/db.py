"""
db.py — Moteur SQLAlchemy + session. Fonctionne sur PostgreSQL (prod) et SQLite (dev).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import get_settings

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
engine = create_engine(settings.db_url, echo=False, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Crée les tables. Import des modèles nécessaire pour peupler le metadata."""
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
