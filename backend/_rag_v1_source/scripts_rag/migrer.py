"""Applique les migrations SQL dans l'ordre.

    python -m scripts.migrer

Avant d'appliquer quoi que ce soit, on vérifie que l'hébergeur fournit les
extensions PostgreSQL dont le schéma dépend. C'est la première chose qui
casse chez un hébergeur mal choisi, et le message d'erreur brut de
PostgreSQL ne dit pas quoi faire. Mieux vaut échouer tôt et clairement.

Note : pgvector est requis même quand les embeddings sont désactivés, car
les colonnes vectorielles font partie du schéma. Sans embeddings, elles
restent simplement vides et la recherche se fait en plein texte seul.
"""

import pathlib
import sys

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.db import engine  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent

EXTENSIONS = {
    "vector": "pgvector, pour les colonnes d'embeddings du référentiel et du RAG",
    "pg_trgm": "pg_trgm, pour la tolérance aux fautes de frappe",
    "unaccent": "unaccent, pour ignorer les accents dans les recherches",
}


def verifier_extensions(conn) -> None:
    """Refuse de migrer si une extension nécessaire est absente de l'hébergeur."""
    disponibles = {
        ligne[0]
        for ligne in conn.execute(text("SELECT name FROM pg_available_extensions"))
    }
    manquantes = [nom for nom in EXTENSIONS if nom not in disponibles]
    if not manquantes:
        return

    print("\nCette base PostgreSQL ne fournit pas les extensions nécessaires :\n")
    for nom in manquantes:
        print(f"  - {nom} ({EXTENSIONS[nom]})")
    print(
        "\nIl ne s'agit pas d'un droit à accorder : l'extension n'est pas installée\n"
        "sur le serveur. Il faut une base qui la propose (voir DEPLOIEMENT.md).\n"
    )
    raise SystemExit(1)


def main() -> None:
    fichiers = sorted(RACINE.glob("migrations/*.sql"))
    if not fichiers:
        print("Aucune migration trouvée.")
        return

    with engine.begin() as conn:
        verifier_extensions(conn)
        for fichier in fichiers:
            print(f"  {fichier.name}")
            conn.execute(text(fichier.read_text(encoding="utf-8")))

    print(f"\n{len(fichiers)} migration(s) appliquée(s).")


if __name__ == "__main__":
    main()
