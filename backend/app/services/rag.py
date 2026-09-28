"""
services/rag.py — RAG léger multi-base (SQLite dev, PostgreSQL prod).

Deux tables (créées automatiquement) :
- rag_documents : source ingérée (organisme, url, version, date d'ingestion).
- rag_passages : morceaux de texte + embedding sérialisé (JSON).

Recherche hybride :
- lexical : LIKE + score basé sur nb de tokens communs (simple mais robuste
  sans dépendance à pg_trgm) ;
- dense : cosinus sur les embeddings (numpy) si le passage en a un ;
- fusion : Reciprocal Rank Fusion (paramètre k=60).

Sans clé d'embeddings, le mode dense est ignoré : la recherche reste
lexicale et le service continue à fonctionner. Les passages retournés
citent leur source, comme pour la version pgvector du projet 2.

Ce module est utilisé par le Conseiller d'orientation (agent 1) ET par le
Chatbot (agent 2) — les deux consultent la même base vectorielle.
"""
from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

RRF_K = 60


# ------------------------------------------------------------ schéma tables
#
# La forme du DDL diffère entre SQLite et PostgreSQL sur deux points :
#   - la colonne d'auto-incrément (INTEGER PRIMARY KEY vs SERIAL) ;
#   - la valeur par défaut d'un booléen (1 vs TRUE).
#
# On construit donc le DDL à l'exécution en lisant le dialecte SQLAlchemy.


def _est_postgres(db: Session) -> bool:
    return db.bind.dialect.name in ("postgresql", "postgres")


def _ddl(postgres: bool) -> list[str]:
    id_col = "id SERIAL PRIMARY KEY" if postgres else "id INTEGER PRIMARY KEY AUTOINCREMENT"
    doc_id_col = "id SERIAL PRIMARY KEY" if postgres else "id INTEGER PRIMARY KEY AUTOINCREMENT"
    actif_defaut = "TRUE" if postgres else "1"
    return [
        f"""
        CREATE TABLE IF NOT EXISTS rag_documents (
          {doc_id_col},
          organisme VARCHAR(120) NOT NULL,
          titre VARCHAR(400) NOT NULL,
          url VARCHAR(800) DEFAULT '',
          version INTEGER DEFAULT 1,
          phase VARCHAR(40) DEFAULT '',
          pays VARCHAR(40) DEFAULT '',
          actif BOOLEAN DEFAULT {actif_defaut},
          ingere_le VARCHAR(40) DEFAULT ''
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS rag_passages (
          {id_col},
          document_id INTEGER NOT NULL,
          titre VARCHAR(400) DEFAULT '',
          contenu TEXT NOT NULL,
          phase VARCHAR(40) DEFAULT '',
          pays VARCHAR(40) DEFAULT '',
          embedding TEXT DEFAULT ''
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_rag_passages_document ON rag_passages(document_id)",
        "CREATE INDEX IF NOT EXISTS idx_rag_passages_phase ON rag_passages(phase)",
    ]


def init_tables(db: Session) -> None:
    """Crée les tables RAG si elles n'existent pas.

    Idempotent : on peut l'appeler à chaque démarrage. Le DDL est adapté
    au dialecte de la base au premier appel.
    """
    for ddl in _ddl(_est_postgres(db)):
        db.execute(text(ddl))
    db.commit()


# ------------------------------------------------------------ modèle simple


@dataclass
class Passage:
    id: int
    titre: str
    contenu: str
    phase: Optional[str]
    document: str
    organisme: str
    url: str
    version: int
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------ tokenisation


_STOP = {"de", "la", "le", "les", "des", "du", "et", "en", "un", "une", "au",
         "aux", "pour", "que", "qui", "avec", "sur", "dans", "par", "ce",
         "cette", "est", "sont", "à", "d", "l", "s"}


def _norm(text_: str) -> str:
    s = unicodedata.normalize("NFD", (text_ or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s


def _tokens(text_: str) -> list[str]:
    s = _norm(text_)
    mots = re.findall(r"[a-z0-9]{2,}", s)
    return [m for m in mots if m not in _STOP]


# ------------------------------------------------------------ embeddings


def _try_encode(requete: str) -> Optional[list[float]]:
    try:
        from app.services import embeddings as emb
        v = emb.encoder(requete)
        return list(v) if v is not None else None
    except Exception as e:  # noqa: BLE001
        logger.debug("Embeddings indisponibles (%s) — recherche lexicale seule", e)
        return None


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


# ------------------------------------------------------------ recherche


def rechercher(
    db: Session,
    requete: str,
    phase: Optional[str] = None,
    pays: Optional[str] = None,
    limite: int = 5,
    candidats: int = 20,
) -> list[Passage]:
    """Recherche hybride BM25-approximative + cosinus sur embeddings.

    Retour : au plus `limite` passages, triés par score de fusion (RRF).
    Chaque passage porte sa source pour que l'agent puisse la citer.
    """
    if not requete or not requete.strip():
        return []

    init_tables(db)

    # Filtre par phase / pays (optionnel). `d.actif` seul est portable :
    # SQLite lit 1 comme truthy, Postgres lit TRUE.
    where = "WHERE d.actif"
    params: dict[str, object] = {}
    if phase:
        where += " AND (p.phase = :phase OR d.phase = :phase)"
        params["phase"] = phase
    if pays:
        where += " AND (p.pays = :pays OR d.pays = :pays OR p.pays = '' OR d.pays = '')"
        params["pays"] = pays

    lignes = db.execute(
        text(
            f"""
            SELECT p.id, p.titre, p.contenu, p.phase, d.titre, d.organisme,
                   d.url, d.version, p.embedding
            FROM rag_passages p
            JOIN rag_documents d ON d.id = p.document_id
            {where}
            LIMIT :cap
            """
        ),
        {**params, "cap": max(candidats * 4, 200)},
    ).fetchall()

    if not lignes:
        return []

    # Rang lexical : nb de tokens communs, normalisé par la taille du passage.
    tokens_req = set(_tokens(requete))
    lex_scores: list[tuple[int, float]] = []
    for i, l in enumerate(lignes):
        toks_p = set(_tokens(l[2]))
        recouv = len(tokens_req & toks_p)
        if recouv == 0:
            continue
        # Un passage court qui recouvre autant est plus pertinent.
        score = recouv / math.log2(2 + len(toks_p))
        lex_scores.append((i, score))
    lex_scores.sort(key=lambda t: -t[1])
    lex_scores = lex_scores[:candidats]

    # Rang dense : cosinus si un embedding est encodable et si le passage
    # a un vecteur stocké.
    vec_q = _try_encode(requete)
    dense_scores: list[tuple[int, float]] = []
    if vec_q:
        for i, l in enumerate(lignes):
            emb = l[8]
            if not emb:
                continue
            try:
                v = json.loads(emb)
                s = _cos(vec_q, v)
                if s > 0:
                    dense_scores.append((i, s))
            except (ValueError, TypeError):
                continue
    dense_scores.sort(key=lambda t: -t[1])
    dense_scores = dense_scores[:candidats]

    # Reciprocal Rank Fusion. Chaque liste apporte 1 / (k + rang).
    fusion: dict[int, float] = {}
    for rang, (i, _s) in enumerate(lex_scores):
        fusion[i] = fusion.get(i, 0.0) + 1.0 / (RRF_K + rang + 1)
    for rang, (i, _s) in enumerate(dense_scores):
        fusion[i] = fusion.get(i, 0.0) + 1.0 / (RRF_K + rang + 1)

    ordre = sorted(fusion.items(), key=lambda t: -t[1])[:limite]

    resultats: list[Passage] = []
    for i, score in ordre:
        l = lignes[i]
        resultats.append(Passage(
            id=int(l[0]), titre=str(l[1] or ""), contenu=str(l[2] or ""),
            phase=(l[3] or None), document=str(l[4] or ""),
            organisme=str(l[5] or ""), url=str(l[6] or ""),
            version=int(l[7] or 1), score=float(score),
        ))
    return resultats


def formater_contexte(passages: list[Passage]) -> str:
    """Met les passages en forme pour un prompt d'agent LLM."""
    if not passages:
        return "(aucun passage pertinent trouvé dans la base de connaissance)"
    blocs = []
    for i, p in enumerate(passages, start=1):
        entete = f"[{i}] {p.titre or p.document} ({p.organisme})"
        blocs.append(f"{entete}\n{p.contenu}")
    return "\n\n".join(blocs)


def sources_citees(passages: list[Passage], numeros: Iterable) -> list[dict]:
    """Traduit les numéros cités dans le JSON du LLM en références réelles."""
    sortie = []
    vus: set[int] = set()
    for n in numeros or []:
        try:
            i = int(n) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(passages) and i not in vus:
            vus.add(i)
            p = passages[i]
            sortie.append({
                "titre": p.titre or p.document,
                "organisme": p.organisme,
                "url": p.url,
                "version": p.version,
            })
    return sortie


# ------------------------------------------------------------ ingestion


def ajouter_document(
    db: Session,
    *,
    organisme: str,
    titre: str,
    url: str = "",
    version: int = 1,
    phase: str = "",
    pays: str = "",
) -> int:
    """Ajoute un document source et retourne son id."""
    init_tables(db)
    now = datetime.utcnow().isoformat(timespec="seconds")
    # Le booléen `actif` et la récupération de l'id doivent s'adapter au
    # dialecte : Postgres refuse `= 1` sur BOOLEAN, et son `SERIAL` ne
    # renseigne pas `lastrowid` — on utilise `RETURNING id`, supporté par
    # SQLite (3.35+) et Postgres.
    actif_val = "TRUE" if _est_postgres(db) else "1"
    r = db.execute(
        text(
            f"""
            INSERT INTO rag_documents (organisme, titre, url, version, phase, pays, actif, ingere_le)
            VALUES (:organisme, :titre, :url, :version, :phase, :pays, {actif_val}, :now)
            RETURNING id
            """
        ),
        {"organisme": organisme, "titre": titre, "url": url, "version": version,
         "phase": phase, "pays": pays, "now": now},
    )
    doc_id = r.scalar()
    db.commit()
    return int(doc_id)


def ajouter_passage(
    db: Session,
    *,
    document_id: int,
    titre: str,
    contenu: str,
    phase: str = "",
    pays: str = "",
    embedding: Optional[list[float]] = None,
) -> None:
    """Ajoute un passage lié à un document.

    L'embedding est optionnel : sans lui, la recherche reste lexicale sur
    ce passage. On peut le poser plus tard via reembedder.
    """
    init_tables(db)
    emb_txt = json.dumps(embedding) if embedding else ""
    db.execute(
        text(
            """
            INSERT INTO rag_passages (document_id, titre, contenu, phase, pays, embedding)
            VALUES (:d, :t, :c, :ph, :pa, :e)
            """
        ),
        {"d": document_id, "t": titre, "c": contenu, "ph": phase, "pa": pays, "e": emb_txt},
    )
    db.commit()


def etat(db: Session) -> dict:
    """État de la base RAG, pour le diagnostic."""
    init_tables(db)
    docs = db.execute(text("SELECT COUNT(*) FROM rag_documents WHERE actif")).scalar() or 0
    passages = db.execute(text("SELECT COUNT(*) FROM rag_passages")).scalar() or 0
    vecs = db.execute(
        text("SELECT COUNT(*) FROM rag_passages WHERE embedding IS NOT NULL AND embedding != ''"),
    ).scalar() or 0
    return {
        "documents_actifs": int(docs),
        "passages": int(passages),
        "passages_vectorises": int(vecs),
        "recherche": "hybride" if vecs else "lexicale seule",
    }
