"""Réconciliation des actions prises hors ligne.

Un seul appel, qui reçoit le lot d'actions accumulées sans réseau et renvoie
l'état réconcilié. Les règles d'arbitrage et leurs limites sont expliquées
dans migrations/011_synchronisation.sql.

Deux types d'action, et pas un de plus
--------------------------------------
« etape » et « profil ». Il n'existe aucun type capable de transporter un
message : la promesse de non-conservation des conversations n'est pas une
consigne de code, c'est une absence de chemin. Une question écrite hors ligne
repart par /api/chatbot/conversation comme n'importe quel appel d'agent.

Le contrat de retour
--------------------
    traitees   le serveur a statué, le client retire ces actions de sa file.
    differees  le serveur n'a pas pu statuer maintenant, le client les garde.
    detail     le verdict par action, pour le journal et pour les tests.
    etat       l'état après réconciliation, pour que le client converge.
    horloge    l'heure du serveur, qui permet au client de repérer une
               horloge locale déréglée et de le dire à l'étudiant.

Rejouer un lot déjà envoyé ne casse rien
----------------------------------------
Si la réponse se perd en route, le client rejoue. Une action rejouée porte le
même horodatage que celui déjà enregistré : elle n'est pas strictement plus
récente, donc elle est classée « anterieure » et le résultat en base est
identique. Il n'y a pas besoin de table d'actions déjà vues, parce que les
deux opérations sont idempotentes par construction.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.comptes import utilisateur_courant
from app.services.metriques import compteurs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/synchronisation", tags=["Synchronisation"])

# Un lot plus gros que cela ne vient pas d'un usage réel. La file coalesce par
# étape : 200 actions supposeraient une feuille de route de 200 étapes.
MAX_ACTIONS = 200

# Tolérance d'avance d'horloge. Au-delà, la date est ramenée à l'heure du
# serveur : une horloge en avance de deux ans gagnerait sinon tous les
# arbitrages futurs, définitivement.
AVANCE_TOLEREE = timedelta(minutes=5)


class Action(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    type: Literal["etape", "profil"]
    horodatage: datetime
    charge: dict[str, Any]


class Lot(BaseModel):
    actions: list[Action] = Field(default_factory=list, max_length=MAX_ACTIONS)


@router.post("")
def synchroniser(
    lot: Lot,
    compte: dict = Depends(utilisateur_courant),
    db: Session = Depends(get_db),
) -> dict:
    maintenant = datetime.now(timezone.utc)
    traitees: list[str] = []
    differees: list[str] = []
    detail: list[dict] = []

    # Les actions sont appliquées dans l'ordre chronologique de l'appareil.
    # Deux actions sur la même étape peuvent se trouver dans un même lot si
    # elles viennent de deux onglets ; l'arbitrage doit alors être le même que
    # si elles étaient arrivées séparément.
    for action in sorted(lot.actions, key=lambda a: a.horodatage):
        date = _borner(action.horodatage, maintenant)

        if action.type == "etape":
            resultat = _appliquer_etape(db, compte["id"], action, date)
        else:
            resultat = _appliquer_profil(db, compte["id"], action, date)

        detail.append({"id": action.id, "resultat": resultat})
        compteurs.incrementer(f"synchronisation.{action.type}.{resultat}")

        if resultat == "differee":
            differees.append(action.id)
        else:
            traitees.append(action.id)

    db.commit()

    if lot.actions:
        logger.info(
            "Synchronisation : %d traitée(s), %d différée(s).",
            len(traitees), len(differees),
        )
        compteurs.incrementer("synchronisation.lot")

    return {
        "traitees": traitees,
        "differees": differees,
        "detail": detail,
        "etat": _etat(db, compte["id"]),
        "horloge": maintenant.isoformat(),
    }


# --------------------------------------------------------------- arbitrage


def _borner(date: datetime, maintenant: datetime) -> datetime:
    """Ramène une date en avance sur le serveur à l'heure du serveur."""
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    if date > maintenant + AVANCE_TOLEREE:
        return maintenant
    return date


def _appliquer_etape(db: Session, utilisateur_id: str, action: Action, date: datetime) -> str:
    index = action.charge.get("index")
    fait = action.charge.get("fait")

    if not isinstance(index, int) or index < 0 or not isinstance(fait, bool):
        return "charge_invalide"

    # FOR UPDATE : deux onglets qui synchronisent en même temps liraient
    # sinon le même horodatage et la seconde écriture perdrait la première.
    ligne = db.execute(
        text(
            "SELECT etapes_faites, etapes_horodatage FROM roadmap_enregistree "
            "WHERE utilisateur_id = :u FOR UPDATE"
        ),
        {"u": utilisateur_id},
    ).fetchone()

    if not ligne:
        # Le compte n'a pas encore de feuille de route enregistrée : la
        # sauvegarde automatique n'est pas encore passée. L'action est gardée
        # par le client et repartira au prochain essai.
        return "differee"

    faites = set(ligne[0] or [])
    horodatages = dict(ligne[1] or {})
    precedent = horodatages.get(str(index))

    if precedent and date <= _lire_date(precedent):
        return "anterieure"

    if fait:
        faites.add(index)
    else:
        faites.discard(index)
    horodatages[str(index)] = date.isoformat()

    db.execute(
        text(
            "UPDATE roadmap_enregistree SET etapes_faites = :f, "
            "etapes_horodatage = CAST(:h AS jsonb), maj_le = now() "
            "WHERE utilisateur_id = :u"
        ),
        {"u": utilisateur_id, "f": sorted(faites), "h": json.dumps(horodatages)},
    )
    return "appliquee"


def _appliquer_profil(db: Session, utilisateur_id: str, action: Action, date: datetime) -> str:
    entrant = action.charge.get("profil")
    if not isinstance(entrant, dict):
        return "charge_invalide"

    ligne = db.execute(
        text(
            "SELECT profil, maj_horodatage FROM orientation_enregistree "
            "WHERE utilisateur_id = :u FOR UPDATE"
        ),
        {"u": utilisateur_id},
    ).fetchone()

    if not ligne:
        db.execute(
            text(
                "INSERT INTO orientation_enregistree (utilisateur_id, profil, maj_horodatage) "
                "VALUES (:u, CAST(:p AS jsonb), :d)"
            ),
            {"u": utilisateur_id, "p": json.dumps(entrant, ensure_ascii=False), "d": date},
        )
        return "appliquee"

    stocke = dict(ligne[0] or {})
    precedent = ligne[1]

    # Fusion champ par champ dans les deux sens : aucun champ n'est jamais
    # perdu. Seule la direction change, donc qui gagne sur un champ que les
    # deux côtés renseignent.
    plus_recent = precedent is None or date > _lire_date(precedent)
    fusion = {**stocke, **entrant} if plus_recent else {**entrant, **stocke}

    if fusion == stocke:
        return "anterieure"

    db.execute(
        text(
            "UPDATE orientation_enregistree SET profil = CAST(:p AS jsonb), "
            "maj_horodatage = :d, maj_le = now() WHERE utilisateur_id = :u"
        ),
        {
            "u": utilisateur_id,
            "p": json.dumps(fusion, ensure_ascii=False),
            # L'horodatage conservé est le plus récent des deux, sinon un
            # profil ancien qui apporte un champ inconnu ferait reculer la
            # date et rouvrirait des arbitrages déjà tranchés.
            "d": date if plus_recent else precedent,
        },
    )
    return "appliquee" if plus_recent else "fusionnee"


def _etat(db: Session, utilisateur_id: str) -> dict:
    """L'état après réconciliation, pour que le client s'aligne dessus."""
    orientation = db.execute(
        text("SELECT profil FROM orientation_enregistree WHERE utilisateur_id = :u"),
        {"u": utilisateur_id},
    ).fetchone()
    roadmap = db.execute(
        text(
            "SELECT etapes_faites, secteurs_payes, chatbot_ouvert "
            "FROM roadmap_enregistree WHERE utilisateur_id = :u"
        ),
        {"u": utilisateur_id},
    ).fetchone()

    return {
        "profil": orientation[0] if orientation else None,
        "etapes_faites": list(roadmap[0]) if roadmap else [],
        "secteurs_payes": list(roadmap[1]) if roadmap else [],
        "chatbot_ouvert": roadmap[2] if roadmap else False,
    }


def _lire_date(valeur: Any) -> datetime:
    """Accepte une date déjà typée ou sa forme texte, toujours en UTC."""
    if isinstance(valeur, datetime):
        date = valeur
    else:
        date = datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
    return date if date.tzinfo else date.replace(tzinfo=timezone.utc)
