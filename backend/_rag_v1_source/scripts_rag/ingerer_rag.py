"""Ingestion de la base de connaissance procédurale.

Charge les documents depuis app/donnees/procedures.json, découpe automatiquement les sections en
chunks, calcule les embeddings et remplit les tables du RAG.

Le versionnage est géré ici : si un document existe déjà avec un contenu
différent, une nouvelle version est créée et l'ancienne est désactivée.
On conserve ainsi l'historique, et on sait sur quelle version de la
connaissance une réponse a été produite.

    python -m scripts.ingerer_rag
    python -m scripts.ingerer_rag --force    # réingère même sans changement
"""

import argparse
import hashlib
import json
import pathlib
import sys

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.db import engine  # noqa: E402
from app.services import embeddings  # noqa: E402
from app.services.chunker import chunker  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent
CORPUS = RACINE / "app" / "donnees" / "procedures.json"


def empreinte(document: dict) -> str:
    """Hachage du contenu, pour détecter un changement réel."""
    contenu = json.dumps(document.get("passages", []), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(contenu.encode("utf-8")).hexdigest()[:32]


def ingerer(force: bool = False) -> None:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    documents = corpus.get("documents", [])
    print(f"{len(documents)} document(s) dans le corpus.\n")

    vectorisation = embeddings.disponible()
    print(
        "Embeddings actifs, recherche hybride."
        if vectorisation
        else "Embeddings indisponibles, la recherche utilisera le plein texte seul."
    )
    print()

    total_passages = 0

    with engine.begin() as conn:
        for doc in documents:
            reference = doc["reference"]
            empr = empreinte(doc)

            existant = conn.execute(
                text(
                    "SELECT id, version, empreinte FROM document_source "
                    "WHERE reference = :ref AND actif"
                ),
                {"ref": reference},
            ).fetchone()

            if existant and existant[2] == empr and not force:
                print(f"  {reference} : inchangé, ignoré")
                continue

            version = (existant[1] + 1) if existant else 1

            if existant:
                conn.execute(
                    text("UPDATE document_source SET actif = FALSE WHERE id = :id"),
                    {"id": existant[0]},
                )
                print(f"  {reference} : nouvelle version {version}")
            else:
                print(f"  {reference} : première ingestion")

            doc_id = conn.execute(
                text(
                    """
                    INSERT INTO document_source
                      (reference, titre, url_officielle, organisme, pays, version, actif, empreinte)
                    VALUES (:ref, :titre, :url, :org, :pays, :version, TRUE, :empr)
                    RETURNING id
                    """
                ),
                {
                    "ref": reference, "titre": doc["titre"], "url": doc["url_officielle"],
                    "org": doc["organisme"], "pays": doc.get("pays"),
                    "version": version, "empr": empr,
                },
            ).scalar()

            passages_source = doc.get("passages", [])

            # Une section éditoriale n'est pas forcément un bon chunk RAG.
            # On la découpe automatiquement avant de calculer les embeddings.
            chunks = []
            for passage in passages_source:
                for chunk in chunker(passage.get("contenu", "")):
                    chunks.append({
                        "titre": passage.get("titre"),
                        "phase": passage.get("phase"),
                        "contenu": chunk.texte,
                        "token_count": chunk.token_count,
                    })

            textes = [
                f"{c.get('titre', '')}. {c['contenu']}" for c in chunks
            ]
            vecteurs = embeddings.encoder_lot(textes) if vectorisation else [None] * len(chunks)

            for ordre, (chunk, vecteur) in enumerate(zip(chunks, vecteurs), start=1):
                conn.execute(
                    text(
                        """
                        INSERT INTO passage
                          (document_id, ordre, titre, contenu, phase,
                           token_count, char_count, contenu_hash, embedding,
                           modele_embedding)
                        VALUES
                          (:doc, :ordre, :titre, :contenu, :phase,
                           :token_count, :char_count, :contenu_hash,
                           CAST(:emb AS vector), :modele_embedding)
                        """
                    ),
                    {
                        "doc": doc_id,
                        "ordre": ordre,
                        "titre": chunk.get("titre"),
                        "contenu": chunk["contenu"],
                        "phase": chunk.get("phase"),
                        "token_count": chunk["token_count"],
                        "char_count": len(chunk["contenu"]),
                        "contenu_hash": hashlib.sha256(
                            chunk["contenu"].encode("utf-8")
                        ).hexdigest()[:32],
                        "emb": embeddings.en_pgvector(vecteur),
                        "modele_embedding": embeddings.modele_actif() if vecteur else None,
                    },
                )
            total_passages += len(chunks)
            print(f"    {len(passages_source)} section(s) -> {len(chunks)} chunk(s)")

    print(f"\n{total_passages} passage(s) ingéré(s).")


def vectoriser_etablissements() -> None:
    """Calcule les embeddings des établissements pour le matching sémantique."""
    if not embeddings.disponible():
        print("Embeddings indisponibles, étape ignorée.")
        return

    with engine.begin() as conn:
        lignes = conn.execute(
            text("SELECT id, nom, description FROM etablissement")
        ).fetchall()

        if not lignes:
            print("Aucun établissement à vectoriser.")
            return

        textes = [f"{l[1]}. {l[2]}" for l in lignes]
        vecteurs = embeddings.encoder_lot(textes)

        for (eid, _, _), vecteur in zip(lignes, vecteurs):
            conn.execute(
                text("UPDATE etablissement SET embedding = CAST(:v AS vector) WHERE id = :id"),
                {"v": embeddings.en_pgvector(vecteur), "id": eid},
            )

    print(f"{len(lignes)} établissement(s) vectorisé(s).")


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description="Ingestion du RAG")
    parseur.add_argument("--force", action="store_true", help="réingère même sans changement")
    args = parseur.parse_args()

    ingerer(force=args.force)
    print()
    vectoriser_etablissements()
