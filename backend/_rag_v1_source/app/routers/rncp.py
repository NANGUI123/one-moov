"""Vérification RNCP.

Lookup déterministe, jamais l'IA. Ces routes lisent une table et rendent ce
qu'elle contient, avec sa source et sa date de vérification. Aucun modèle
n'intervient : un code RNCP inventé ressemble trait pour trait à un vrai,
et l'étudiant n'a aucun moyen de faire la différence.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(prefix="/api/rncp", tags=["RNCP"])

_CHAMPS = """
    f.code, f.numero, f.intitule, f.niveau_europeen, f.portee,
    f.certificateur, f.etat_reel, f.echeance, f.echue,
    f.jours_avant_echeance, f.remplace_par, f.source_url,
    f.verifie_le, f.a_reverifier
"""


def _fiche(ligne) -> dict:
    return {
        "code": ligne[0],
        "numero": ligne[1],
        "intitule": ligne[2],
        "niveau_europeen": ligne[3],
        "niveau_libelle": {6: "licence", 7: "master"}.get(ligne[3]),
        "portee": ligne[4],
        "certificateur": ligne[5],
        "etat": ligne[6],
        "echeance": ligne[7].isoformat() if ligne[7] else None,
        "echue": ligne[8],
        "jours_avant_echeance": ligne[9],
        "remplace_par": ligne[10],
        "source_url": ligne[11],
        "verifie_le": ligne[12].isoformat(),
        "a_reverifier": ligne[13],
    }


@router.get("/etablissement/{etablissement_id}")
def par_etablissement(etablissement_id: str, db: Session = Depends(get_db)) -> dict:
    """Les fiches rattachées à un établissement, chaîne de remplacement suivie."""
    # DISTINCT ON la fiche résolue : un établissement rattaché à la fois à
    # une ancienne fiche et à celle qui la remplace verrait sinon la même
    # fiche deux fois, les deux chaînes aboutissant au même code.
    # On garde le rattachement le plus récemment vérifié.
    lignes = db.execute(
        text(
            f"""
            SELECT DISTINCT ON (f.code)
                   {_CHAMPS}, er.niveau, er.certificateur_verifie, er.note
            FROM etablissement_rncp er
            JOIN fiche_rncp_reelle f ON f.code = fiche_en_vigueur(er.code_rncp)
            WHERE er.etablissement_id = :e
            ORDER BY f.code, er.verifie_le DESC
            """
        ),
        {"e": etablissement_id},
    ).fetchall()

    return {
        "etablissement_id": etablissement_id,
        "fiches": [
            {
                **_fiche(l),
                "niveau_demande": l[14],
                "certificateur_verifie": l[15],
                "note": l[16],
            }
            for l in lignes
        ],
    }


@router.get("/{code}")
def par_code(code: str, db: Session = Depends(get_db)) -> dict:
    """Une fiche par son code. Redirige vers la fiche en vigueur si remplacée."""
    code = code.upper().strip()
    if not code.startswith("RNCP"):
        code = f"RNCP{code}"

    ligne = db.execute(
        text(f"SELECT {_CHAMPS} FROM fiche_rncp_reelle f WHERE f.code = :c"),
        {"c": code},
    ).fetchone()

    if not ligne:
        raise HTTPException(
            404,
            "Cette fiche n'est pas dans notre référentiel. "
            "Vérifie-la directement sur francecompetences.fr.",
        )

    fiche = _fiche(ligne)

    if fiche["remplace_par"]:
        remplacante = db.execute(
            text(f"SELECT {_CHAMPS} FROM fiche_rncp_reelle f WHERE f.code = fiche_en_vigueur(:c)"),
            {"c": code},
        ).fetchone()
        if remplacante:
            fiche["fiche_en_vigueur"] = _fiche(remplacante)

    return fiche
