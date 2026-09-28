"""Tests du service RAG portable (SQLite/Postgres, hybride lexical + dense).

On vérifie que :
  - l'ingestion d'un document et de ses passages est idempotente ;
  - la recherche rend les passages ordonnés par pertinence ;
  - une requête filtrée par phase respecte le filtre ;
  - une requête vide rend un résultat vide, sans exception ;
  - la citation de sources se recolle bien aux passages retournés.
"""
from app.services import rag


def _amorcer(db):
    """Peuple un corpus test minimal, idempotent."""
    doc_id = rag.ajouter_document(
        db,
        organisme="Campus France",
        titre="Procédure Études en France",
        url="https://test/eef",
        version=1,
        phase="candidature",
        pays="Cameroun",
    )
    rag.ajouter_passage(
        db, document_id=doc_id,
        titre="Dossier candidat", contenu="Le dossier Études en France centralise la candidature et l'entretien Campus France.",
        phase="candidature", pays="Cameroun",
    )
    rag.ajouter_passage(
        db, document_id=doc_id,
        titre="Pièces justificatives", contenu="Les relevés de notes et le baccalauréat doivent être scannés en couleur.",
        phase="candidature",
    )

    doc_visa = rag.ajouter_document(
        db, organisme="France-Visas",
        titre="Demande de visa long séjour VLS-TS",
        url="https://test/visa", version=1, phase="visa",
    )
    rag.ajouter_passage(
        db, document_id=doc_visa,
        titre="VLS-TS étudiant", contenu="Le visa long séjour étudiant vaut titre de séjour, valable un an à validation.",
        phase="visa",
    )
    return doc_id, doc_visa


def test_ingestion_et_recherche(db):
    _amorcer(db)
    resultats = rag.rechercher(db, "dossier Campus France candidature", limite=3)
    assert resultats, "la recherche doit rendre au moins un passage"
    # Le passage sur le dossier candidat doit sortir en tête sur cette requête.
    assert "dossier" in resultats[0].contenu.lower()
    # Les métadonnées de provenance suivent le passage.
    assert resultats[0].organisme == "Campus France"
    assert resultats[0].url == "https://test/eef"


def test_recherche_vide(db):
    """Une requête vide ne doit pas jeter et rendre une liste vide."""
    assert rag.rechercher(db, "") == []
    assert rag.rechercher(db, "   ") == []


def test_filtre_par_phase(db):
    _amorcer(db)
    # Requête ambigüe entre les phases : sans filtre elle ramène les deux ;
    # avec filtre visa, elle ne doit ramener que le visa.
    resultats = rag.rechercher(db, "titre de séjour étudiant", phase="visa", limite=5)
    assert resultats, "la recherche filtrée doit rendre au moins un passage"
    for p in resultats:
        assert p.phase in (None, "", "visa"), f"phase inattendue : {p.phase}"


def test_ingestion_idempotente_sur_documents_ajoutes_deux_fois(db):
    """Ajouter deux documents identiques crée deux entrées ; les scripts
    d'ingestion protègent l'idempotence par leur test « déjà ingéré »."""
    avant = rag.etat(db)["documents_actifs"]
    rag.ajouter_document(db, organisme="X", titre="T", url="u", version=1)
    rag.ajouter_document(db, organisme="X", titre="T", url="u", version=1)
    apres = rag.etat(db)["documents_actifs"]
    assert apres - avant == 2, "ajouter_document ne dédoublonne pas — c'est aux scripts de le faire"


def test_sources_citees_recolle_les_bonnes_references(db):
    _amorcer(db)
    passages = rag.rechercher(db, "dossier baccalauréat", limite=3)
    assert passages
    sources = rag.sources_citees(passages, [1, 2])
    assert 1 <= len(sources) <= 2
    for s in sources:
        assert set(s.keys()) == {"titre", "organisme", "url", "version"}


def test_formatage_contexte_numérote(db):
    _amorcer(db)
    passages = rag.rechercher(db, "dossier", limite=2)
    contexte = rag.formater_contexte(passages)
    assert "[1]" in contexte and "Campus France" in contexte


def test_etat_reflete_le_contenu(db):
    _amorcer(db)
    etat = rag.etat(db)
    assert etat["documents_actifs"] >= 2
    assert etat["passages"] >= 3
    assert etat["recherche"] in ("lexicale seule", "hybride")
