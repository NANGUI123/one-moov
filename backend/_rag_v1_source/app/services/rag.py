"""RAG : récupération de la connaissance procédurale.

La recherche est hybride. Un classement dense sur les embeddings capte la
reformulation, un classement lexical retrouve les termes exacts que le dense
rate (« VLS-TS », un numéro de formulaire). Les deux sont fusionnés par
Reciprocal Rank Fusion dans la fonction SQL rechercher_passages.

Point important pour la fiabilité : ce module ne renvoie jamais un montant
ni une date. Il renvoie du procédural, avec la source et la version du
document. Les valeurs chiffrées viennent du module faits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.services import embeddings

logger = logging.getLogger(__name__)

_SQL_RECHERCHE = text(
    """
    SELECT passage_id, titre, contenu, phase, document_titre,
           organisme, url_officielle, version, score
    FROM rechercher_passages(
        CAST(:emb AS vector), :requete, :phase, :pays, :candidats, :limite
    )
    """
)


@dataclass
class Passage:
    """Un extrait de procédure officielle, avec sa provenance."""

    id: int
    titre: Optional[str]
    contenu: str
    phase: Optional[str]
    document: str
    organisme: str
    url: str
    version: int
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


def rechercher(
    db: Session,
    requete: str,
    phase: Optional[str] = None,
    pays: Optional[str] = None,
    limite: Optional[int] = None,
) -> list[Passage]:
    """Retrouve les passages les plus pertinents pour une question."""
    if not requete or not requete.strip():
        return []

    vecteur = embeddings.en_pgvector(embeddings.encoder(requete))

    lignes = db.execute(
        _SQL_RECHERCHE,
        {
            "emb": vecteur,
            "requete": requete,
            "phase": phase,
            "pays": pays,
            "candidats": settings.rag_candidats,
            "limite": limite or settings.rag_top_k,
        },
    ).fetchall()

    return [
        Passage(
            id=l[0], titre=l[1], contenu=l[2], phase=l[3], document=l[4],
            organisme=l[5], url=l[6], version=l[7], score=float(l[8]),
        )
        for l in lignes
    ]


def formater_contexte(passages: list[Passage]) -> str:
    """Met les passages en forme pour le prompt de l'agent.

    Chaque passage est numéroté afin que le modèle puisse citer sa source.
    On lui demandera de renvoyer les numéros utilisés, ce qui permet
    d'afficher les vraies références à l'étudiant.
    """
    if not passages:
        return "(aucun passage pertinent trouvé dans la base de connaissance)"

    blocs = []
    for i, p in enumerate(passages, start=1):
        entete = f"[{i}] {p.titre or p.document} ({p.organisme})"
        blocs.append(f"{entete}\n{p.contenu}")
    return "\n\n".join(blocs)


def sources_citees(passages: list[Passage], numeros: list) -> list[dict]:
    """Traduit les numéros cités par le modèle en références réelles."""
    sortie = []
    vus = set()
    for n in numeros or []:
        try:
            index = int(n) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(passages) and index not in vus:
            vus.add(index)
            p = passages[index]
            sortie.append(
                {
                    "titre": p.titre or p.document,
                    "organisme": p.organisme,
                    "url": p.url,
                    "version": p.version,
                }
            )
    return sortie


def etat(db: Session) -> dict:
    """État de la base de connaissance, pour le diagnostic."""
    ligne = db.execute(
        text(
            """
            SELECT
              (SELECT COUNT(*) FROM document_source WHERE actif),
              (SELECT COUNT(*) FROM passage),
              (SELECT COUNT(*) FROM passage WHERE embedding IS NOT NULL),
              (SELECT MAX(ingere_le) FROM document_source WHERE actif)
            """
        )
    ).fetchone()

    total_passages = ligne[1] or 0
    avec_vecteur = ligne[2] or 0
    return {
        "documents_actifs": ligne[0] or 0,
        "passages": total_passages,
        "passages_vectorises": avec_vecteur,
        "recherche": "hybride" if avec_vecteur else "plein texte seul",
        "derniere_ingestion": ligne[3].isoformat() if ligne[3] else None,
    }
