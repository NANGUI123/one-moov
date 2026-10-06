"""
db.py — Moteur SQLAlchemy + session. Fonctionne sur PostgreSQL (prod) et SQLite (dev).
"""
import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import get_settings

logger = logging.getLogger(__name__)
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


def _colonne_si_manquante(nom_table: str, definition: str) -> None:
    """Ajoute une colonne à une table existante si elle n'y est pas déjà.

    `create_all` ne modifie jamais une table existante — c'est intentionnel,
    mais laisse orphelines les colonnes ajoutées par un déploiement plus
    récent. Cette petite migration comble le trou en s'appuyant sur
    l'inspecteur SQLAlchemy (SQLite et PostgreSQL le supportent).

    `definition` est écrit en SQL brut : `nom TYPE DEFAULT ...`. Le premier
    mot est le nom de la colonne, utilisé pour la détection.
    """
    inspecteur = inspect(engine)
    if nom_table not in inspecteur.get_table_names():
        return
    nom_colonne = definition.split()[0]
    colonnes_existantes = {c["name"] for c in inspecteur.get_columns(nom_table)}
    if nom_colonne in colonnes_existantes:
        return
    with engine.connect() as conn:
        conn.execute(text(f"ALTER TABLE {nom_table} ADD COLUMN {definition}"))
        conn.commit()
    logger.info("Migration : colonne %s.%s ajoutée", nom_table, nom_colonne)


def init_db() -> None:
    """Crée les tables + applique les micro-migrations additives.

    Aucune migration retirée ou destructive n'est faite ici : on ne
    supprime jamais de colonne au démarrage, c'est le rôle d'un vrai
    outil de migration (Alembic) si un jour on en ajoute un.
    """
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # Ajouts de colonnes rétrocompatibles.
    _colonne_si_manquante("users", "pays_residence VARCHAR(80) DEFAULT ''")
    _colonne_si_manquante("rncp_fiches", "remplace_par VARCHAR(20) NOT NULL DEFAULT ''")
