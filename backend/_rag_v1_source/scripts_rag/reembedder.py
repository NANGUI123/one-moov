"""Ré-embedde tout le corpus, en une fois.

    python -m scripts.reembedder            # ré-embedde ce qui manque
    python -m scripts.reembedder --tout     # ré-embedde absolument tout

À lancer après un changement de fournisseur ou de modèle d'embeddings.

Pourquoi « en une fois » plutôt qu'au fil de l'eau
--------------------------------------------------
Les vecteurs de deux modèles vivent dans des espaces sans rapport. S'ils
coexistent dans la même colonne, la recherche mélange des distances qui ne
veulent rien dire l'une par rapport à l'autre — et elle ne lève aucune
erreur. Le symptôme est une pertinence qui se dégrade sans raison visible.

Le script vérifie donc que tout le corpus porte le même modèle à la fin, et
le dit franchement si ce n'est pas le cas.

L'index HNSW est reconstruit à la fin : un index construit sur des vecteurs
absents puis rempli au fur et à mesure donne de moins bons résultats qu'un
index bâti sur des données complètes.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402
from app.services import embeddings  # noqa: E402

LOT = 32


def _embedder_table(db, table: str, colonnes_texte: str, tout: bool) -> tuple[int, int]:
    """Renvoie (lignes embeddées, lignes qui auraient dû l'être).

    Les deux chiffres, et non le seul premier : une ligne demandée mais non
    embeddée est le symptôme d'une clé refusée ou d'un quota atteint. Sans ce
    second compteur, le script ne distinguerait pas « rien à faire » de
    « tout a échoué », et sortirait en succès dans les deux cas.
    """

    modele = embeddings.modele_actif()

    condition = "TRUE" if tout else (
        "embedding IS NULL OR modele_embedding IS DISTINCT FROM :modele"
    )
    lignes = db.execute(
        text(f"SELECT id::text, {colonnes_texte} FROM {table} WHERE {condition}"),
        {"modele": modele} if not tout else {},
    ).fetchall()

    if not lignes:
        print(f"  {table} : rien à faire")
        return 0, 0

    print(f"  {table} : {len(lignes)} ligne(s) à embedder")
    traites = 0

    for debut in range(0, len(lignes), LOT):
        tranche = lignes[debut : debut + LOT]
        textes = [" ".join(str(c or "") for c in ligne[1:]).strip() for ligne in tranche]
        vecteurs = embeddings.encoder_lot(textes)

        for (identifiant, *_), vecteur in zip(tranche, vecteurs):
            if vecteur is None:
                continue
            db.execute(
                text(
                    f"UPDATE {table} SET embedding = CAST(:v AS vector), "
                    f"  modele_embedding = :m WHERE id = :i"
                ),
                {"v": embeddings.en_pgvector(vecteur), "m": modele, "i": identifiant},
            )
            traites += 1

        db.commit()
        print(f"    {min(debut + LOT, len(lignes))}/{len(lignes)}")

    return traites, len(lignes)


def main() -> None:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--tout", action="store_true",
        help="ré-embedde même les lignes déjà au bon modèle",
    )
    arguments = analyseur.parse_args()

    if not embeddings.disponible():
        print(
            "\nLes embeddings ne sont pas configurés.\n"
            "Pose EMBEDDINGS_ENABLED=true et la clé du fournisseur, puis relance.\n"
            "Sans eux, la recherche fonctionne en plein texte français seul.\n"
        )
        raise SystemExit(1)

    modele = embeddings.modele_actif()
    print(f"Modèle : {modele} ({embeddings.dimensions()} dimensions)\n")

    db = SessionLocal()

    total = attendu = 0
    for table, colonnes in (("passage", "titre, contenu"),
                            ("etablissement", "nom, description")):
        faits, demandes = _embedder_table(db, table, colonnes, arguments.tout)
        total += faits
        attendu += demandes

    if total == 0 and attendu > 0:
        # Des lignes attendaient un vecteur et aucune ne l'a reçu : la clé est
        # refusée, le quota est atteint, ou le fournisseur est injoignable. Le
        # message de repli est déjà passé plus haut. Sortir en succès ici
        # ferait croire à un corpus embeddé, et la recherche resterait en
        # plein texte sans que personne ne s'en aperçoive.
        print(
            f"\n{attendu} ligne(s) attendaient un vecteur, aucune ne l'a reçu.\n"
            "La recherche continue de fonctionner en plein texte français, mais\n"
            "les embeddings ne servent à rien en l'état. Vérifie la clé :\n"
            "  python -m scripts.verifier_cles\n"
        )
        db.close()
        raise SystemExit(1)

    if total == 0:
        print("\nRien n'a été modifié.")
        db.close()
        return

    # Vérification : tout le corpus doit porter le même modèle.
    print("\nVérification de la cohérence…")
    incoherent = False
    for table in ("passage", "etablissement"):
        modeles = db.execute(
            text(
                f"SELECT COALESCE(modele_embedding, '(vide)'), count(*) "
                f"FROM {table} WHERE embedding IS NOT NULL "
                f"GROUP BY 1 ORDER BY 2 DESC"
            )
        ).fetchall()
        for nom, nombre in modeles:
            marque = " " if nom == modele else "  ATTENTION :"
            print(f" {marque} {table} — {nom} : {nombre}")
            if nom != modele:
                incoherent = True

    if incoherent:
        print(
            "\nPlusieurs modèles cohabitent dans la même colonne. La recherche "
            "renverra du bruit sans lever d'erreur.\n"
            "Relance avec --tout pour tout remettre d'aplomb.\n"
        )
        db.close()
        raise SystemExit(1)

    # L'index est reconstruit sur des données complètes : c'est là qu'il
    # donne ses meilleurs résultats.
    print("\nReconstruction des index HNSW…")
    for index, table, colonne in (
        ("idx_passage_embedding", "passage", "embedding"),
        ("idx_etab_embedding", "etablissement", "embedding"),
    ):
        db.execute(text(f"DROP INDEX IF EXISTS {index}"))
        db.execute(
            text(
                f"CREATE INDEX {index} ON {table} "
                f"USING hnsw ({colonne} vector_cosine_ops)"
            )
        )
        db.commit()
        print(f"  {index}")

    print(f"\n{total} vecteur(s) écrit(s). Recherche hybride opérationnelle.")
    db.close()


if __name__ == "__main__":
    main()
