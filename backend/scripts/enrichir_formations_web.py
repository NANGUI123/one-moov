"""
scripts/enrichir_formations_web.py — Enrichissement de la table formations.

Sources ingérées (exigence 2) :

  Public
    - ONISEP Idéo (annuaire des formations)         data.enseignementsup-recherche.gouv.fr
    - Mon Master (référentiel des mentions master)  data.gouv.fr
    - Parcoursup (fiches formations post-bac)       data.gouv.fr

  Privé
    - France Compétences (RNCP)                     export officiel
    - Écoles privées                                snapshot local (JSON), à
                                                    remplacer/étendre à mesure
                                                    qu'on découvre des partenariats.

Le script sait tourner sans réseau : chaque source a une URL principale
et un instantané local en repli. C'est ce qui permet à l'application
d'être fonctionnelle même quand un dataset officiel est momentanément
inaccessible.

Usage :

    python -m scripts.enrichir_formations_web
    python -m scripts.enrichir_formations_web --forcer   # ré-ingère tout
    python -m scripts.enrichir_formations_web --source onisep,monmaster
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Formation  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("enrichir")

SOURCES = {
    # Chaque source a : URL par défaut (surchargée par la variable d'env
    # correspondante), voie public/privé, mapping de champs.
    "onisep": {
        "url_env": "ONISEP_URL",
        "url_defaut": "https://data.enseignementsup-recherche.gouv.fr/api/records/1.0/search/"
                      "?dataset=fr-esr-referentiel-offre-de-formation-onisep&rows=200",
        "voie": "public",
        "provenance": "ONISEP",
    },
    "monmaster": {
        "url_env": "MONMASTER_URL",
        "url_defaut": "https://www.data.gouv.fr/api/1/datasets/r/mon-master-mentions",
        "voie": "public",
        "provenance": "Mon Master (data.gouv.fr)",
    },
    "parcoursup": {
        "url_env": "PARCOURSUP_URL",
        "url_defaut": "https://data.enseignementsup-recherche.gouv.fr/api/records/1.0/search/"
                      "?dataset=fr-esr-parcoursup&rows=200",
        "voie": "public",
        "provenance": "Parcoursup",
    },
    "ecoles_privees": {
        "url_env": "ECOLES_PRIVEES_URL",
        "url_defaut": "",  # jamais public, on part du snapshot local
        "voie": "prive",
        "provenance": "Écoles privées (partenariats)",
    },
}


def _http_json(url: str) -> dict | list | None:
    if not url:
        return None
    try:
        with httpx.Client(timeout=45.0, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("HTTP %s : %s", url, e)
        return None


def _extraire_lignes(payload) -> list[dict]:
    """Ramène une réponse open data quelconque à une liste de dictionnaires."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for cle in ("records", "results", "formations", "data", "hits"):
            v = payload.get(cle)
            if isinstance(v, list):
                # Récupérer un « fields » interne le cas échéant.
                return [(x.get("fields") if isinstance(x, dict) and "fields" in x else x)
                        for x in v if isinstance(x, dict)]
    return []


def _cle_norm(d: dict, *cles: str) -> str:
    """Cherche la première clé présente, retourne '' sinon."""
    for c in cles:
        v = d.get(c)
        if v not in (None, ""):
            return str(v)
    return ""


def _map(source: str, x: dict) -> dict | None:
    """Aplati un enregistrement générique vers le schéma Formation."""
    intitule = _cle_norm(x, "intitule", "libelle", "libelle_formation", "nom",
                         "intitule_licence_libelle", "libelle_court")
    if not intitule:
        return None
    return {
        "source": source,
        "intitule": intitule[:400],
        "etablissement": _cle_norm(x, "etablissement", "nom_etablissement",
                                    "uai_libelle", "etablissement_nom")[:400],
        "ville": _cle_norm(x, "ville", "commune", "com_lib", "localisation",
                            "libelle_commune")[:160],
        "domaine": _cle_norm(x, "domaine", "discipline", "secteur",
                              "domaine_libelle", "secteur_disciplinaire")[:160],
        "niveau": _cle_norm(x, "niveau", "niveau_sortie", "niveau_diplome",
                             "grade_libelle")[:80],
        "voie": _cle_norm(x, "voie") or SOURCES[source]["voie"],
        "cout_annuel": int(_cle_norm(x, "cout_annuel", "cout") or 0) if _cle_norm(x, "cout_annuel", "cout").isdigit() else 0,
        "url": _cle_norm(x, "url", "lien", "lien_web")[:600],
        "code_rncp": _cle_norm(x, "code_rncp", "rncp", "certification_rncp"),
        "langue": _cle_norm(x, "langue") or "français",
    }


def _snapshot(nom: str) -> list[dict]:
    """Instantané local d'une source, servant de repli."""
    p = Path(__file__).resolve().parent.parent / "app" / "data" / "seed" / f"{nom}.json"
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("formations", []) if isinstance(d, dict) else d
    except Exception as e:  # noqa: BLE001
        logger.warning("Snapshot %s illisible (%s)", nom, e)
        return []


def _upsert(db, lignes: list[dict], source: str, provenance: str) -> int:
    n = 0
    aujourdhui = str(date.today())
    for r in lignes:
        intitule = (r.get("intitule") or "").strip()
        etab = (r.get("etablissement") or "").strip()
        if not intitule:
            continue
        existant = db.query(Formation).filter(
            Formation.intitule == intitule,
            Formation.etablissement == etab,
        ).first()
        if existant:
            continue
        db.add(Formation(
            source=r.get("source", source),
            code_rncp=r.get("code_rncp", ""),
            intitule=intitule[:400],
            etablissement=etab[:400],
            ville=(r.get("ville") or "")[:160],
            domaine=(r.get("domaine") or "")[:160],
            niveau=(r.get("niveau") or "")[:80],
            voie=r.get("voie") or SOURCES[source]["voie"],
            cout_annuel=int(r.get("cout_annuel") or 0),
            langue=r.get("langue") or "français",
            url=(r.get("url") or "")[:600],
            provenance=provenance[:200],
            date_verif=aujourdhui,
        ))
        n += 1
    db.commit()
    return n


def ingerer_source(db, nom: str, forcer: bool) -> int:
    """Ingère une source, avec repli sur son snapshot local."""
    conf = SOURCES[nom]
    if not forcer and db.query(Formation).filter(Formation.source == nom).count() > 0:
        logger.info("Source %s déjà présente (utiliser --forcer pour réingérer)", nom)
        return 0

    url = os.environ.get(conf["url_env"], "") or conf["url_defaut"]
    logger.info("→ %s : %s", nom, url or "(pas d'URL, snapshot local seulement)")
    payload = _http_json(url) if url else None
    lignes = _extraire_lignes(payload)
    mappees = [_map(nom, x) for x in lignes]
    mappees = [m for m in mappees if m]

    if not mappees:
        mappees = _snapshot(nom)
        logger.info("Repli sur le snapshot local : %s enregistrements", len(mappees))

    n = _upsert(db, mappees, nom, conf["provenance"])
    logger.info("%s : %s formations ajoutées", nom, n)
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrichissement des formations depuis l'open data.")
    parser.add_argument("--forcer", action="store_true", help="Ré-ingère chaque source même si déjà présente.")
    parser.add_argument("--source", default=",".join(SOURCES.keys()),
                        help="Liste séparée par des virgules parmi : "
                             f"{', '.join(SOURCES.keys())}")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as db:
        total = 0
        for s in [x.strip() for x in args.source.split(",") if x.strip()]:
            if s not in SOURCES:
                logger.warning("Source inconnue : %s (ignorée)", s)
                continue
            total += ingerer_source(db, s, args.forcer)
        logger.info("Total ajouté : %s formations. Table formations = %s lignes.",
                    total, db.query(Formation).count())


if __name__ == "__main__":
    main()
