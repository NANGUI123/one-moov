"""Fixtures pytest : base de test isolée, client HTTP FastAPI, seed minimal.

Chaque test s'exécute contre une base SQLite en fichier temporaire, montée
avant l'import de l'application, puis effacée après la session. Cela évite
que les tests polluent la base de développement locale et qu'un test en
casse un autre.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# On isole la base AVANT d'importer app.* : les modules SQLAlchemy lisent
# DATABASE_URL au chargement.
_TMP_DIR = tempfile.mkdtemp(prefix="onemoov-tests-")
_DB_FILE = Path(_TMP_DIR) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE}"
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-prod")
os.environ.setdefault("EMAIL_VERIFICATION_REQUISE", "false")
# Neutralise les fournisseurs externes dans les tests unitaires :
# les tests qui veulent l'IA doivent poser leur propre mock explicite.
os.environ.setdefault("GROQ_API_KEY", "")
os.environ.setdefault("RNCP_LLM_API_KEY", "")
os.environ.setdefault("SMTP_HOST", "")

# Rend l'arborescence backend/ importable comme "app.*" en local.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Base, engine, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services import rag  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _base_de_test():
    """Crée le schéma une fois pour toute la session, l'efface à la fin."""
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        rag.init_tables(db)
    yield
    Base.metadata.drop_all(bind=engine)
    try:
        _DB_FILE.unlink()
    except FileNotFoundError:
        pass


@pytest.fixture()
def db():
    """Session SQLAlchemy pour les tests unitaires qui touchent la base."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client():
    """Client HTTP monté sur l'app FastAPI, en mémoire (pas de serveur réseau)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def settings():
    """Accès aux settings résolus, utile pour vérifier la configuration."""
    return get_settings()
