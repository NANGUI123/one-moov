"""Connexion à la base de données.

Une session par requête, fermée automatiquement. L'application ne conserve
aucune donnée d'étudiant : la base ne contient que du référentiel (écoles,
villes, faits vérifiés, documents du RAG).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    """Dépendance FastAPI : ouvre une session, la ferme quoi qu'il arrive."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
