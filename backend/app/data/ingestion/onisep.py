"""
data/ingestion/onisep.py — Alimentation de la table `formations`.

Stratégie : on tente l'ingestion depuis l'open data (URL configurable :
OPEN_DATA_FORMATIONS_URL, ex. un export ONISEP Idéo / Mon Master / Parcoursup au
format JSON). Si indisponible ou non configurée, on charge l'instantané de repli
pour que l'application fonctionne quand même.

Chaque fiche garde sa provenance et sa date de vérification (traçabilité).
"""
import os
import json
import logging
from datetime import date
from pathlib import Path
import httpx
from sqlalchemy.orm import Session
from app.models import Formation

logger = logging.getLogger(__name__)
SEED = Path(__file__).resolve().parent.parent / "seed" / "formations_fallback.json"


def _upsert(db: Session, rows: list[dict], provenance: str) -> int:
    n = 0
    for r in rows:
        intitule = (r.get("intitule") or "").strip()
        etab = (r.get("etablissement") or "").strip()
        if not intitule:
            continue
        exists = db.query(Formation).filter(
            Formation.intitule == intitule, Formation.etablissement == etab).first()
        if exists:
            continue
        db.add(Formation(
            source=r.get("source", provenance),
            code_rncp=r.get("code_rncp", ""),
            intitule=intitule, etablissement=etab,
            ville=r.get("ville", ""), domaine=r.get("domaine", ""),
            niveau=r.get("niveau", ""), voie=r.get("voie", "public"),
            cout_annuel=int(r.get("cout_annuel") or 0), langue=r.get("langue", "français"),
            url=r.get("url", ""), provenance=provenance,
            date_verif=str(date.today()),
        ))
        n += 1
    db.commit()
    return n


def seed_from_fallback(db: Session) -> int:
    data = json.loads(SEED.read_text(encoding="utf-8"))
    return _upsert(db, data.get("formations", []), provenance="instantané de repli (à vérifier)")


def ingest_open_data(db: Session) -> int:
    """Tente l'ingestion depuis l'open data. Retourne le nombre de fiches ajoutées."""
    url = os.getenv("OPEN_DATA_FORMATIONS_URL", "").strip()
    if not url:
        logger.info("OPEN_DATA_FORMATIONS_URL non définie — repli sur l'instantané seed")
        return seed_from_fallback(db)
    try:
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        rows = payload if isinstance(payload, list) else payload.get("results") or payload.get("formations") or []
        rows = [_map_record(x) for x in rows]
        n = _upsert(db, [r for r in rows if r], provenance=f"open data ({url})")
        logger.info(f"Ingestion open data : {n} formations")
        return n or seed_from_fallback(db)
    except Exception as e:
        logger.warning(f"Ingestion open data échouée ({e}) — repli sur l'instantané seed")
        return seed_from_fallback(db)


def _map_record(x: dict) -> dict | None:
    """Mappe un enregistrement open data générique vers notre schéma.
    À adapter aux champs exacts du dataset choisi (ONISEP Idéo, Mon Master…)."""
    if not isinstance(x, dict):
        return None
    intitule = x.get("intitule") or x.get("libelle") or x.get("libelle_formation") or x.get("nom")
    if not intitule:
        return None
    return {
        "intitule": intitule,
        "etablissement": x.get("etablissement") or x.get("nom_etablissement") or x.get("uai_libelle") or "",
        "ville": x.get("ville") or x.get("commune") or x.get("localisation") or "",
        "domaine": x.get("domaine") or x.get("discipline") or x.get("secteur") or "",
        "niveau": x.get("niveau") or x.get("niveau_sortie") or "",
        "voie": x.get("voie") or ("prive" if str(x.get("secteur", "")).lower().startswith("priv") else "public"),
        "cout_annuel": x.get("cout_annuel") or 0,
        "url": x.get("url") or x.get("lien") or "",
        "code_rncp": x.get("code_rncp") or x.get("rncp") or "",
        "source": "open_data",
    }


def charger_formations(db: Session, force: bool = False) -> int:
    # Sur une base déjà peuplée, on ne renvoie 0 QUE si le référentiel couvre
    # bien les nouveaux domaines du seed (Environnement, Communication,
    # Social, Tourisme, Agriculture). Sinon on relance l'ingestion : le
    # _upsert n'écrase pas les formations déjà connues, il n'ajoute que
    # celles qui manquent. Ça met à niveau une base d'un déploiement
    # antérieur sans intervention manuelle.
    if not force:
        nb = db.query(Formation).count()
        if nb > 0:
            nouveaux_domaines = ["Environnement Écologie", "Communication Médias",
                                 "Social Éducation", "Tourisme Hôtellerie", "Agriculture Agronomie"]
            manque = db.query(Formation).filter(
                Formation.domaine.in_(nouveaux_domaines)).count() == 0
            if not manque:
                return 0
    return ingest_open_data(db)
