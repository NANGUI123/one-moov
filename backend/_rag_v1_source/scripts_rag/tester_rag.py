"""Diagnostic du pipeline RAG One Moov.

Usage:
    python -m scripts.tester_rag "quelles pièces préparer pour le visa"
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402
from app.services import rag  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("requete", help="question à tester")
    parser.add_argument("--phase", default=None)
    parser.add_argument("--pays", default=None)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        print("=== ÉTAT RAG ===")
        print(rag.etat(db))
        print("\n=== RETRIEVAL ===")
        passages = rag.rechercher(
            db,
            args.requete,
            phase=args.phase,
            pays=args.pays,
            limite=5,
        )
        for i, passage in enumerate(passages, 1):
            print(
                f"\n[{i}] score={passage.score} | "
                f"{passage.document} | {passage.organisme} | "
                f"phase={passage.phase}"
            )
            print(passage.contenu[:700])
            print(f"Source: {passage.url}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
