"""Faits critiques : les valeurs qui ne passent jamais par le modèle.

Frais, seuils de ressources, quotas d'heures, délais. Une valeur fausse sur
ces sujets coûte cher à l'étudiant, donc elle vient de la base, avec sa
source et sa date de vérification, et jamais d'une génération.

Chaque fait renvoyé porte l'indication de sa fraîcheur. Au-delà de quatre-vingt-dix
jours sans contrôle, il est signalé comme à revérifier, et l'interface
l'affiche différemment.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class Fait:
    cle: str
    categorie: str
    libelle: str
    valeur: str
    unite: Optional[str]
    pays: Optional[str]
    source_url: str
    source_libelle: str
    verifie_le: str
    jours_depuis_verification: int
    a_reverifier: bool

    def to_dict(self) -> dict:
        return asdict(self)

    def phrase(self) -> str:
        """Formulation lisible, telle qu'elle sera montrée à l'étudiant."""
        unite = f" {self.unite}" if self.unite else ""
        return f"{self.libelle} : {self.valeur}{unite}"


_SQL_PAR_PAYS = text(
    """
    SELECT cle, categorie, libelle, valeur, unite, pays,
           source_url, source_libelle, verifie_le,
           jours_depuis_verification, a_reverifier
    FROM fait_en_vigueur
    WHERE (pays IS NULL OR pays = :pays)
      AND (:categorie IS NULL OR categorie::text = :categorie)
    ORDER BY (pays IS NULL), categorie, cle
    """
)

_SQL_PAR_CLE = text(
    """
    SELECT cle, categorie, libelle, valeur, unite, pays,
           source_url, source_libelle, verifie_le,
           jours_depuis_verification, a_reverifier
    FROM fait_en_vigueur
    WHERE cle = :cle AND (pays IS NULL OR pays = :pays)
    ORDER BY (pays IS NULL)
    LIMIT 1
    """
)


def _construire(ligne) -> Fait:
    return Fait(
        cle=ligne[0], categorie=ligne[1], libelle=ligne[2], valeur=ligne[3],
        unite=ligne[4], pays=ligne[5], source_url=ligne[6], source_libelle=ligne[7],
        verifie_le=ligne[8].isoformat(), jours_depuis_verification=int(ligne[9]),
        a_reverifier=bool(ligne[10]),
    )


def pour_pays(db: Session, pays: Optional[str], categorie: Optional[str] = None) -> list[Fait]:
    """Tous les faits en vigueur applicables à un pays."""
    lignes = db.execute(_SQL_PAR_PAYS, {"pays": pays, "categorie": categorie}).fetchall()
    return [_construire(l) for l in lignes]


def par_cle(db: Session, cle: str, pays: Optional[str] = None) -> Optional[Fait]:
    """Un fait précis. Le fait spécifique au pays prime sur le fait général."""
    ligne = db.execute(_SQL_PAR_CLE, {"cle": cle, "pays": pays}).fetchone()
    return _construire(ligne) if ligne else None


def formater_pour_prompt(faits: list[Fait]) -> str:
    """Met les faits à disposition du modèle, avec une consigne explicite.

    Le modèle a le droit de citer ces valeurs parce qu'elles sont vérifiées.
    Il n'a pas le droit d'en inventer d'autres.
    """
    if not faits:
        return "(aucune valeur officielle disponible pour ce pays)"

    lignes = [
        f"- {f.libelle} : {f.valeur}{' ' + f.unite if f.unite else ''}"
        f" (source : {f.source_libelle}, vérifié le {f.verifie_le})"
        for f in faits
    ]
    return "\n".join(lignes)
