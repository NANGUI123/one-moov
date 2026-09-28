"""Paiement mobile money.

Un principe, dont tout le reste découle :

    LE WEBHOOK N'EST PAS LA SOURCE DE VÉRITÉ.

N'importe qui connaissant l'URL de notification peut poster un faux
« paiement confirmé » et débloquer une feuille de route sans payer. C'est la
faille la plus banale de ce type d'intégration. Ici, un webhook ne fait que
déclencher une re-interrogation de l'API de statut du fournisseur ; seul le
résultat de cette seconde requête est écrit en base.

Trois fournisseurs :

    pawapay   Le seul agrégateur qui couvre à la fois le Cameroun
              (MTN, Orange) et le Congo-Brazzaville (MTN, Airtel).
    manuel    L'étudiant paie sur un numéro marchand existant et saisit sa
              référence ; un administrateur valide. Moins élégant, mais
              n'attend la validation d'aucun tiers.
    mock      Simulation, pour le développement et la démonstration.

Sur les opérateurs : Orange Money n'existe pas au Congo-Brazzaville. Les
deux opérateurs y sont MTN et Airtel. Une liste d'opérateurs codée en dur
« MTN + Orange » pour les deux pays serait fausse pour la moitié de la
cible.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass

import httpx

from app.config import settings
from app.services.metriques import compteurs

logger = logging.getLogger(__name__)


class ErreurPaiement(Exception):
    """Le fournisseur n'a pas pu traiter la demande."""


# --- Opérateurs réellement disponibles, par pays -------------------------
#
# Les codes correspondent aux « correspondents » pawaPay. Une erreur ici se
# traduit par un paiement refusé chez l'opérateur, sans message utile.
OPERATEURS: dict[str, dict[str, str]] = {
    "Cameroun": {
        "mtn": "MTN_MOMO_CMR",
        "orange": "ORANGE_CMR",
    },
    "Congo-Brazzaville": {
        "mtn": "MTN_MOMO_COG",
        "airtel": "AIRTEL_COG",
    },
}

# Plancher imposé par les opérateurs et les agrégateurs. Un tarif affiché
# en dessous ne serait tout simplement pas encaissable.
MONTANT_MINIMUM_FCFA = 100


@dataclass
class Demande:
    """Ce qu'on envoie au fournisseur pour créer un paiement."""

    paiement_id: str
    montant_fcfa: int
    pays: str
    operateur: str
    telephone: str
    description: str


@dataclass
class Etat:
    """Ce que le fournisseur dit d'un paiement. Le seul écrit qui fait foi."""

    statut: str           # en_attente | en_cours | reussi | echoue
    reference: str | None = None
    motif: str | None = None


def operateurs_du_pays(pays: str) -> list[str]:
    return sorted(OPERATEURS.get(pays, {}))


def verifier_operateur(pays: str, operateur: str) -> str:
    """Traduit un opérateur en code fournisseur, ou refuse explicitement."""
    disponibles = OPERATEURS.get(pays)
    if not disponibles:
        raise ErreurPaiement(f"Le paiement n'est pas ouvert pour : {pays}")
    code = disponibles.get(operateur.lower())
    if not code:
        raise ErreurPaiement(
            f"{operateur} n'est pas disponible en {pays}. "
            f"Opérateurs possibles : {', '.join(sorted(disponibles))}."
        )
    return code


def normaliser_telephone(numero: str, pays: str) -> str:
    """Met le numéro au format international attendu par les fournisseurs."""
    chiffres = "".join(c for c in numero if c.isdigit())
    indicatifs = {"Cameroun": "237", "Congo-Brazzaville": "242"}
    indicatif = indicatifs.get(pays, "")

    if chiffres.startswith("00"):
        chiffres = chiffres[2:]
    if indicatif and not chiffres.startswith(indicatif):
        chiffres = indicatif + chiffres.lstrip("0")

    if not 8 <= len(chiffres) <= 15:
        raise ErreurPaiement("Ce numéro de téléphone ne semble pas valide.")
    return chiffres


# =========================================================================
# pawaPay
# =========================================================================


def _entetes_pawapay() -> dict[str, str]:
    if not settings.pawapay_token:
        raise ErreurPaiement("pawaPay n'est pas configuré.")
    return {
        "Authorization": f"Bearer {settings.pawapay_token}",
        "Content-Type": "application/json",
    }


def _base_pawapay() -> str:
    return (
        "https://api.sandbox.pawapay.io"
        if settings.pawapay_sandbox
        else "https://api.pawapay.io"
    )


def _demander_pawapay(demande: Demande) -> Etat:
    correspondant = verifier_operateur(demande.pays, demande.operateur)
    charge = {
        "depositId": demande.paiement_id,     # notre identifiant, donc idempotent
        "amount": str(demande.montant_fcfa),
        "currency": "XAF",
        "payer": {
            "type": "MMO",
            "accountDetails": {
                "phoneNumber": demande.telephone,
                "provider": correspondant,
            },
        },
        "customerMessage": demande.description[:22],  # affiché sur le téléphone
    }

    try:
        with httpx.Client(timeout=40) as client:
            reponse = client.post(
                f"{_base_pawapay()}/v2/deposits",
                headers=_entetes_pawapay(),
                json=charge,
            )
    except httpx.RequestError as e:
        raise ErreurPaiement(f"pawaPay injoignable : {e}") from e

    if reponse.status_code >= 400:
        raise ErreurPaiement(f"pawaPay a refusé la demande : {reponse.text[:200]}")

    corps = reponse.json()
    statut = (corps.get("status") or "").upper()
    if statut == "REJECTED":
        motif = (corps.get("failureReason") or {}).get("failureMessage", "refusé")
        return Etat(statut="echoue", motif=motif)

    return Etat(statut="en_cours", reference=demande.paiement_id)


def _etat_pawapay(paiement_id: str) -> Etat:
    """Interroge l'API de statut. C'est cette réponse qui fait autorité."""
    try:
        with httpx.Client(timeout=30) as client:
            reponse = client.get(
                f"{_base_pawapay()}/v2/deposits/{paiement_id}",
                headers=_entetes_pawapay(),
            )
    except httpx.RequestError as e:
        raise ErreurPaiement(f"pawaPay injoignable : {e}") from e

    if reponse.status_code == 404:
        return Etat(statut="en_attente")
    if reponse.status_code >= 400:
        raise ErreurPaiement(f"pawaPay : {reponse.status_code} {reponse.text[:200]}")

    corps = reponse.json()
    donnees = corps.get("data") or corps
    if isinstance(donnees, list):
        donnees = donnees[0] if donnees else {}

    brut = (donnees.get("status") or "").upper()
    correspondance = {
        "COMPLETED": "reussi",
        "ACCEPTED": "en_cours",
        "SUBMITTED": "en_cours",
        "PROCESSING": "en_cours",
        "FAILED": "echoue",
        "REJECTED": "echoue",
    }
    statut = correspondance.get(brut, "en_cours")
    motif = (donnees.get("failureReason") or {}).get("failureMessage")
    return Etat(statut=statut, reference=donnees.get("depositId"), motif=motif)


def verifier_signature_pawapay(corps: bytes, entetes: dict) -> bool:
    """Vérifie la signature du webhook.

    Attention : chez pawaPay la signature est OPTIONNELLE et désactivée par
    défaut. Il faut l'activer explicitement dans le tableau de bord. Tant
    qu'elle ne l'est pas, cette fonction renvoie False et le webhook est
    traité comme un simple déclencheur — ce qui reste sûr, puisque le statut
    vient de toute façon de l'API et jamais du corps du message.
    """
    signature = entetes.get("signature") or entetes.get("x-signature")
    if not signature or not settings.pawapay_signature_secret:
        return False
    attendue = base64.b64encode(
        hmac.new(
            settings.pawapay_signature_secret.encode(), corps, hashlib.sha256
        ).digest()
    ).decode()
    return hmac.compare_digest(signature.strip(), attendue)


# =========================================================================
# Mode manuel : paiement hors ligne, réconcilié par un administrateur
# =========================================================================


def _demander_manuel(demande: Demande) -> Etat:
    """Rien à appeler : l'étudiant paie sur le numéro marchand affiché.

    Le paiement reste « en attente » jusqu'à ce qu'un administrateur le
    valide après avoir retrouvé la transaction sur le relevé marchand.
    """
    return Etat(statut="en_attente")


def _etat_manuel(paiement_id: str) -> Etat:
    # Aucune API à interroger : seule une validation humaine fait avancer
    # ce paiement. La réconciliation ne doit donc pas le clore d'office.
    return Etat(statut="en_attente")


# =========================================================================
# Mock
# =========================================================================


def _demander_mock(demande: Demande) -> Etat:
    return Etat(statut="reussi", reference=f"mock-{uuid.uuid4().hex[:12]}")


def _etat_mock(paiement_id: str) -> Etat:
    return Etat(statut="reussi", reference=f"mock-{paiement_id[:12]}")


# =========================================================================
# Aiguillage
# =========================================================================

_FOURNISSEURS = {
    "pawapay": (_demander_pawapay, _etat_pawapay),
    "manuel": (_demander_manuel, _etat_manuel),
    "mock": (_demander_mock, _etat_mock),
}


def fournisseur_actif() -> str:
    nom = (settings.paiement_fournisseur or "mock").lower()
    return nom if nom in _FOURNISSEURS else "mock"


def demander(demande: Demande) -> Etat:
    nom = fournisseur_actif()
    compteurs.incrementer(f"paiement.demande.{nom}")
    return _FOURNISSEURS[nom][0](demande)


def etat(paiement_id: str) -> Etat:
    """Interroge le fournisseur. Cette réponse, et elle seule, fait autorité."""
    nom = fournisseur_actif()
    compteurs.incrementer(f"paiement.verification.{nom}")
    return _FOURNISSEURS[nom][1](paiement_id)


def info() -> dict:
    nom = fournisseur_actif()
    return {
        "fournisseur": nom,
        "mode": "sandbox" if settings.pawapay_sandbox else "production",
        "configure": nom != "pawapay" or bool(settings.pawapay_token),
        "pays_ouverts": {p: sorted(o) for p, o in OPERATEURS.items()},
        "montant_minimum_fcfa": MONTANT_MINIMUM_FCFA,
    }
