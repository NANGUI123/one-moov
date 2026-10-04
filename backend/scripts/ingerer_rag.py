"""
scripts/ingerer_rag.py — Peuple la base vectorielle du conseiller d'orientation.

Trois sources sont ingérées :

  1. procedures.json      Corpus procédural d'amorçage (Études en France, VLS-TS,
                          entretien Campus France, logement, arrivée). Fournit le
                          fond dont l'agent 2 a besoin dès le premier démarrage.

  2. Table `formations`   Chaque formation (intitulé + établissement + ville +
                          niveau + coût) devient un passage court, ce qui
                          permet au RAG d'orientation de retrouver une
                          formation à partir d'un mot-clé du récit étudiant.

  3. Fiches RNCP          Chaque fiche synchronisée (rncp_fiches) devient un
                          passage pour que le conseiller puisse citer un
                          titre reconnu quand l'étudiant demande.

Les embeddings sont posés si `services/embeddings.py` peut encoder (clé
Mistral / OpenAI ou modèle local). Sinon les passages restent indexés en
lexical, la recherche fonctionne quand même.

Usage :

    python -m scripts.ingerer_rag
    python -m scripts.ingerer_rag --sans-embedding    # ingestion rapide
    python -m scripts.ingerer_rag --reinit            # vide tout et recommence

Ce script fabrique la base vectorielle demandée dans le cahier des charges
(exigence 7). L'ingestion est idempotente : un lancement répété ne double
pas les entrées, il ne prend que ce qui manque.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, init_db  # noqa: E402
from app.services import rag  # noqa: E402
from app.models import Formation, RncpFiche  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("ingerer_rag")

DONNEES = Path(__file__).resolve().parent.parent / "app" / "donnees"


def _encoder(morceau: str, actif: bool) -> list[float] | None:
    if not actif:
        return None
    try:
        from app.services import embeddings as emb
        v = emb.encoder(morceau)
        return list(v) if v is not None else None
    except Exception as e:  # noqa: BLE001
        logger.debug("Encodage indisponible sur ce passage (%s)", e)
        return None


def _reinit(db) -> None:
    """Vide les tables RAG. À utiliser quand le corpus change de version."""
    db.execute(text("DELETE FROM rag_passages"))
    db.execute(text("DELETE FROM rag_documents"))
    db.commit()
    logger.info("Tables RAG remises à zéro.")


def _deja_ingere(db, titre: str, version: int) -> bool:
    """Ce document est-il déjà en base ?

    La comparaison porte sur le TITRE, pas sur l'URL. Deux sections d'une
    même procédure citent légitimement la même page officielle : « la
    procédure Études en France » et « l'entretien Campus France » renvoient
    toutes deux vers la plateforme. Avec l'URL comme clé, la seconde était
    tenue pour déjà ingérée et disparaissait sans un mot — six passages sur
    trente, dont toute la section entretien, qui est le cœur du produit.

    Le symptôme était invisible : le journal annonçait « 6 documents, 24
    passages ajoutés » sans signaler qu'un document avait été sauté.
    """
    row = db.execute(
        text("SELECT 1 FROM rag_documents WHERE titre = :t AND version = :v LIMIT 1"),
        {"t": titre, "v": version},
    ).fetchone()
    return row is not None


def ingerer_procedures(db, avec_embedding: bool) -> tuple[int, int]:
    """Ingestion du corpus procédural fourni.

    Retourne (nb_documents, nb_passages) ajoutés.
    """
    chemin = DONNEES / "procedures.json"
    if not chemin.exists():
        logger.warning("procedures.json absent (%s), on saute", chemin)
        return 0, 0

    corpus = json.loads(chemin.read_text(encoding="utf-8"))
    docs_ajoutes = 0
    passages_ajoutes = 0

    vus: set[str] = set()
    for doc in corpus.get("documents", []):
        url = doc.get("url_officielle") or doc.get("reference") or ""
        titre = doc.get("titre", "Sans titre")
        version = int(doc.get("version") or 1)

        # Un titre en double dans le fichier source ferait disparaître le
        # second document à la prochaine exécution. Autant le dire tout de
        # suite plutôt que de le découvrir en mesurant le rappel.
        if titre in vus:
            logger.warning("Titre de document en double dans procedures.json : "
                           "« %s ». Le second sera ignoré au prochain "
                           "lancement.", titre)
        vus.add(titre)

        if _deja_ingere(db, titre, version):
            continue

        doc_id = rag.ajouter_document(
            db,
            organisme=doc.get("organisme", "Officiel"),
            titre=titre,
            url=url,
            version=version,
            phase="",
            pays=(doc.get("pays") or "") or "",
        )
        docs_ajoutes += 1

        for passage in doc.get("passages", []):
            contenu = (passage.get("contenu") or "").strip()
            if not contenu:
                continue
            vec = _encoder(contenu, avec_embedding)
            rag.ajouter_passage(
                db,
                document_id=doc_id,
                titre=passage.get("titre", ""),
                contenu=contenu,
                phase=passage.get("phase", "") or "",
                pays=(doc.get("pays") or "") or "",
                embedding=vec,
            )
            passages_ajoutes += 1
    return docs_ajoutes, passages_ajoutes


def ingerer_formations(db, avec_embedding: bool) -> tuple[int, int]:
    """Chaque formation devient un passage court dans le RAG.

    Cela permet au conseiller de retrouver des formations à partir de mots
    du récit de l'étudiant, en complément du scoring déterministe.
    """
    doc_id = None
    row = db.execute(
        text("SELECT id FROM rag_documents WHERE url = :u AND version = :v LIMIT 1"),
        {"u": "internal://formations", "v": 1},
    ).fetchone()
    if row:
        doc_id = int(row[0])
    else:
        doc_id = rag.ajouter_document(
            db,
            organisme="Base One Moov",
            titre="Catalogue des formations vérifiées",
            url="internal://formations",
            version=1,
            phase="candidature",
            pays="",
        )

    formations = db.query(Formation).all()
    n = 0
    for f in formations:
        # Un passage déjà présent pour cet id de formation ? On saute.
        existe = db.execute(
            text("SELECT 1 FROM rag_passages WHERE document_id = :d AND titre = :t LIMIT 1"),
            {"d": doc_id, "t": f"formation:{f.id}"},
        ).fetchone()
        if existe:
            continue
        contenu = (
            f"{f.intitule} — {f.etablissement} ({f.ville})."
            f" Domaine : {f.domaine or 'non précisé'}."
            f" Niveau : {f.niveau or 'non précisé'}."
            f" Voie : {f.voie or 'public'}."
            f" Coût annuel : {f.cout_annuel or 'non précisé'} €."
            + (f" Code RNCP : {f.code_rncp}." if f.code_rncp else "")
            + (f" Fiche : {f.url}" if f.url else "")
        )
        vec = _encoder(contenu, avec_embedding)
        rag.ajouter_passage(
            db,
            document_id=doc_id,
            titre=f"formation:{f.id}",
            contenu=contenu,
            phase="candidature",
            pays="",
            embedding=vec,
        )
        n += 1
    return (1 if n else 0), n


def ingerer_rncp(db, avec_embedding: bool) -> tuple[int, int]:
    """Chaque fiche RNCP devient un passage.

    L'étudiant pose souvent des questions du type « ce titre est-il reconnu ? » ;
    avoir ces fiches dans le RAG permet au conseiller de citer directement la
    source France Compétences.
    """
    doc_id = None
    row = db.execute(
        text("SELECT id FROM rag_documents WHERE url = :u AND version = :v LIMIT 1"),
        {"u": "https://www.francecompetences.fr/recherche/rncp/", "v": 1},
    ).fetchone()
    if row:
        doc_id = int(row[0])
    else:
        doc_id = rag.ajouter_document(
            db,
            organisme="France Compétences",
            titre="Répertoire national des certifications professionnelles",
            url="https://www.francecompetences.fr/recherche/rncp/",
            version=1,
            phase="candidature",
            pays="",
        )

    fiches = db.query(RncpFiche).all()
    n = 0
    for fi in fiches:
        existe = db.execute(
            text("SELECT 1 FROM rag_passages WHERE document_id = :d AND titre = :t LIMIT 1"),
            {"d": doc_id, "t": fi.code_rncp},
        ).fetchone()
        if existe:
            continue
        contenu = (
            f"Titre : {fi.intitule}. "
            f"Numéro RNCP : {fi.code_rncp}. "
            f"Niveau : {fi.niveau or 'non précisé'}. "
            f"État : {'actif' if fi.actif else 'inactif'}. "
            f"Certificateurs : {fi.certificateurs or 'non précisé'}. "
            f"Date de fin d'enregistrement : {fi.date_fin or 'non précisée'}."
        )
        vec = _encoder(contenu, avec_embedding)
        rag.ajouter_passage(
            db,
            document_id=doc_id,
            titre=fi.code_rncp,
            contenu=contenu,
            phase="candidature",
            pays="",
            embedding=vec,
        )
        n += 1
    return (1 if n else 0), n


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestion du corpus RAG One Moov.")
    parser.add_argument("--reinit", action="store_true",
                        help="Vide les tables RAG avant d'ingérer.")
    parser.add_argument("--sans-embedding", action="store_true",
                        help="Ingère sans encoder — plus rapide, recherche lexicale seulement.")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as db:
        rag.init_tables(db)
        if args.reinit:
            _reinit(db)

        avec_emb = not args.sans_embedding
        d1, p1 = ingerer_procedures(db, avec_emb)
        logger.info("Procédures : %s documents, %s passages ajoutés.", d1, p1)

        d2, p2 = ingerer_formations(db, avec_emb)
        logger.info("Formations : %s document (catalogue), %s passages ajoutés.", d2, p2)

        d3, p3 = ingerer_rncp(db, avec_emb)
        logger.info("Fiches RNCP : %s document (répertoire), %s passages ajoutés.", d3, p3)

        etat = rag.etat(db)
        logger.info("Base vectorielle : %s", etat)


if __name__ == "__main__":
    main()
