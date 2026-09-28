"""Paiements : création, webhook, consultation.

La règle tenue partout dans ce fichier : **aucun statut n'est jamais écrit
à partir du corps d'un webhook**. Un webhook déclenche une re-interrogation
de l'API du fournisseur, et c'est la réponse de cette API qui est écrite.

Sans cela, n'importe qui connaissant l'URL de notification pourrait poster
un faux « paiement confirmé » et débloquer une feuille de route sans payer.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.routers.comptes import utilisateur_optionnel
from app.services import paiement as svc
from app.services.metriques import compteurs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/paiements", tags=["Paiements"])

# Ce que chaque objet coûte, et ce qu'il débloque. Le tarif vit ici, côté
# serveur : un montant envoyé par le navigateur serait modifiable.
TARIFS: dict[str, int] = {
    "roadmap_public": 130000,
    "roadmap_prive": 130000,
    "roadmap_deux": 130000,
    "correction_orientation": 10000,
}


PAYS_PAIEMENT = {"Cameroun", "Congo-Brazzaville"}


class Creation(BaseModel):
    objet: str
    pays: str
    operateur: str
    telephone: str = Field(min_length=6, max_length=25)


@router.get("/options")
def options() -> dict:
    """Ce qui est payable, par qui, et avec quel opérateur.

    L'interface lit ces valeurs plutôt que de les coder en dur : les
    opérateurs disponibles ne sont pas les mêmes d'un pays à l'autre.
    """
    return {
        **svc.info(),
        "tarifs_fcfa": TARIFS,
        "numero_marchand": (
            settings.paiement_numero_marchand
            if svc.fournisseur_actif() == "manuel"
            else None
        ),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def creer(
    corps: Creation,
    compte: dict | None = Depends(utilisateur_optionnel),
    db: Session = Depends(get_db),
) -> dict:
    """Crée un paiement et le pousse chez le fournisseur."""
    montant = TARIFS.get(corps.objet)
    if montant is None:
        raise HTTPException(422, "Objet de paiement inconnu.")
    if corps.pays not in PAYS_PAIEMENT:
        raise HTTPException(422, "Choisis un pays de résidence pris en charge.")
    if montant < svc.MONTANT_MINIMUM_FCFA:
        # Garde-fou : un tarif sous le plancher opérateur ne serait pas
        # encaissable, et l'échec surviendrait côté étudiant.
        raise HTTPException(
            500, f"Tarif mal configuré : minimum {svc.MONTANT_MINIMUM_FCFA} FCFA."
        )

    try:
        svc.verifier_operateur(corps.pays, corps.operateur)
        telephone = svc.normaliser_telephone(corps.telephone, corps.pays)
    except svc.ErreurPaiement as e:
        raise HTTPException(422, str(e)) from e

    paiement_id = str(uuid.uuid4())
    fournisseur = svc.fournisseur_actif()

    db.execute(
        text(
            "INSERT INTO paiement (id, utilisateur_id, objet, montant_fcfa, pays, "
            "  operateur, telephone, fournisseur, prochaine_verification) "
            "VALUES (:i, :u, CAST(:o AS objet_paiement), :m, :p, :op, :t, :f, "
            "        now() + interval '20 seconds')"
        ),
        {
            "i": paiement_id, "u": compte["id"] if compte else None,
            "o": corps.objet, "m": montant, "p": corps.pays,
            "op": corps.operateur.lower(), "t": telephone, "f": fournisseur,
        },
    )
    db.commit()

    try:
        etat = svc.demander(
            svc.Demande(
                paiement_id=paiement_id,
                montant_fcfa=montant,
                pays=corps.pays,
                operateur=corps.operateur,
                telephone=telephone,
                description="One Moov",
            )
        )
    except svc.ErreurPaiement as e:
        _ecrire_statut(db, paiement_id, "echoue", motif=str(e))
        raise HTTPException(502, f"Le paiement n'a pas pu être lancé : {e}") from e

    _ecrire_statut(db, paiement_id, etat.statut, reference=etat.reference, motif=etat.motif)

    return {
        "paiement_id": paiement_id,
        "statut": etat.statut,
        "montant_fcfa": montant,
        "fournisseur": fournisseur,
        "instruction": _instruction(fournisseur, etat.statut, montant),
    }


@router.get("/{paiement_id}")
def consulter(paiement_id: str, db: Session = Depends(get_db)) -> dict:
    """Consulte un paiement, en re-interrogeant le fournisseur si besoin.

    C'est cet appel que l'interface répète pendant que l'étudiant valide sur
    son téléphone. Il sert aussi de filet quand le webhook n'arrive jamais.
    """
    ligne = db.execute(
        text("SELECT statut::text, objet::text, montant_fcfa, fournisseur, motif_echec "
             "FROM paiement WHERE id = :i"),
        {"i": paiement_id},
    ).fetchone()
    if not ligne:
        raise HTTPException(404, "Paiement introuvable.")

    statut = ligne[0]
    if statut in ("en_attente", "en_cours") and ligne[3] != "manuel":
        try:
            etat = svc.etat(paiement_id)
            if etat.statut != statut:
                _ecrire_statut(db, paiement_id, etat.statut,
                               reference=etat.reference, motif=etat.motif)
                statut = etat.statut
        except svc.ErreurPaiement as e:
            # On ne fait pas échouer la consultation : l'étudiant verra
            # simplement que c'est encore en cours.
            logger.warning("Vérification de %s impossible : %s", paiement_id, e)

    return {
        "paiement_id": paiement_id,
        "statut": statut,
        "objet": ligne[1],
        "montant_fcfa": ligne[2],
        "motif": ligne[4],
    }


@router.post("/webhook/{fournisseur}", include_in_schema=False)
async def webhook(fournisseur: str, requete: Request, db: Session = Depends(get_db)) -> dict:
    """Reçoit une notification de paiement.

    Trois précautions, dans cet ordre :

    1. On répond 200 vite. Un traitement lent provoque un timeout côté
       fournisseur, qui considère la livraison échouée et rejoue.
    2. On ne lit JAMAIS le statut dans le corps. On en extrait seulement
       l'identifiant, puis on interroge l'API de statut.
    3. Le traitement est idempotent : un paiement déjà clos n'est pas
       retouché. Les fournisseurs rejouent leurs webhooks, c'est normal.
    """
    corps_brut = await requete.body()
    compteurs.incrementer(f"paiement.webhook.{fournisseur}")

    if fournisseur == "pawapay":
        entetes = {k.lower(): v for k, v in requete.headers.items()}
        if settings.pawapay_signature_secret and not svc.verifier_signature_pawapay(
            corps_brut, entetes
        ):
            compteurs.incrementer("paiement.webhook.signature_invalide")
            logger.warning("Webhook pawaPay à signature invalide, ignoré.")
            # 200 quand même : renvoyer une erreur ferait rejouer
            # indéfiniment un message qu'on refuse de toute façon.
            return {"recu": True}

    try:
        donnees = await requete.json()
    except Exception:  # noqa: BLE001
        return {"recu": True}

    paiement_id = (
        donnees.get("depositId") or donnees.get("transaction_id") or donnees.get("id")
    )
    if not paiement_id:
        return {"recu": True}

    ligne = db.execute(
        text("SELECT statut::text FROM paiement WHERE id = :i"), {"i": paiement_id}
    ).fetchone()
    if not ligne:
        logger.warning("Webhook pour un paiement inconnu : %s", paiement_id)
        return {"recu": True}

    if ligne[0] in ("reussi", "echoue", "abandonne"):
        # Déjà clos : le weblook est un doublon. C'est le comportement
        # normal d'un fournisseur de paiement, pas une anomalie.
        compteurs.incrementer("paiement.webhook.doublon")
        return {"recu": True}

    try:
        etat = svc.etat(paiement_id)
    except svc.ErreurPaiement as e:
        logger.warning("Webhook reçu mais vérification impossible : %s", e)
        return {"recu": True}

    _ecrire_statut(db, paiement_id, etat.statut, reference=etat.reference, motif=etat.motif)
    return {"recu": True}


# --------------------------------------------------------------- internes


def _ecrire_statut(
    db: Session,
    paiement_id: str,
    statut: str,
    reference: str | None = None,
    motif: str | None = None,
) -> None:
    """Seul endroit du code qui écrit un statut de paiement."""
    clos = statut in ("reussi", "echoue", "abandonne")
    db.execute(
        text(
            "UPDATE paiement SET statut = CAST(:s AS statut_paiement), "
            "  reference_fournisseur = COALESCE(:r, reference_fournisseur), "
            "  motif_echec = COALESCE(:m, motif_echec), "
            "  verifications = verifications + 1, "
            "  clos_le = CASE WHEN :c THEN now() ELSE clos_le END, "
            "  prochaine_verification = CASE WHEN :c THEN NULL "
            "       ELSE now() + interval '30 seconds' END "
            "WHERE id = :i"
        ),
        {"s": statut, "r": reference, "m": motif, "c": clos, "i": paiement_id},
    )
    db.commit()
    if statut == "reussi":
        compteurs.incrementer("paiement.reussi")


def _instruction(fournisseur: str, statut: str, montant: int) -> str:
    if fournisseur == "manuel":
        return (
            f"Envoie {montant} FCFA au {settings.paiement_numero_marchand or '(numéro à configurer)'}, "
            "puis saisis la référence de la transaction. Un administrateur "
            "validera ton paiement."
        )
    if statut == "en_cours":
        return "Valide le paiement sur ton téléphone, puis reviens ici."
    if statut == "reussi":
        return "Paiement confirmé."
    return "Le paiement n'a pas abouti."
