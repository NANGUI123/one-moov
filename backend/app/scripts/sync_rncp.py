"""
Synchronise le référentiel RNCP depuis l'export officiel France Compétences.

    python -m app.scripts.sync_rncp

À lancer une fois au démarrage, puis périodiquement (l'export est quotidien).
"""
import logging
from app.db import SessionLocal, init_db
from app.data.ingestion import rncp

logging.basicConfig(level=logging.INFO)


def main():
    init_db()
    db = SessionLocal()
    try:
        n = rncp.sync(db)
        print(f"✅ RNCP synchronisé : {n} fiches chargées.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
