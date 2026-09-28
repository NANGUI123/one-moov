"""Embeddings.

Pourquoi une API plutôt qu'un modèle local
-------------------------------------------
Un modèle multilingue local ne tient pas dans les 512 Mo du plan
d'hébergement. Le coupable n'est pas le transformeur lui-même (21 M
paramètres, ~85 Mo) mais la table d'embeddings du vocabulaire multilingue :
250 000 entrées × 384 dimensions, matérialisées en flottants 32 bits, soit
~384 Mo de RAM — avec un pic au double pendant le chargement. Mesuré, pas
supposé. Avec FastAPI à côté, on dépasse avant même la première requête.

Passer à PyTorch aggrave le problème (image Docker de ~2 Go). ONNX Runtime
allège l'image mais pas la mémoire, parce que la table de vocabulaire reste
la même.

Un appel HTTP, lui, coûte 0 Mo de RAM et 0 Mo d'image. C'est le seul choix
qui fait disparaître la contrainte.

Le choix de Mistral
-------------------
Fournisseur européen avec un endpoint UE explicite, et très bon en français
sur les tâches de recherche. Ce point n'est pas cosmétique : embedder la
question d'un étudiant, c'est l'envoyer à un tiers à chaque requête. La loi
camerounaise n° 2024/017 soumet les transferts de données vers l'étranger à
autorisation préalable, et un sous-traitant européen est plus simple à
défendre qu'un américain.

Ce qui est envoyé, et rien d'autre : le texte de la question. Jamais
d'identifiant de compte, de session ou d'adresse.

Trois précautions
-----------------
- Un cache mémoire sur les requêtes. Les questions d'étudiants se répètent
  énormément (« quelles pièces pour mon dossier »), et une question déjà
  vue ne repart pas chez le fournisseur.
- En cas d'échec, on renvoie None plutôt que de lever : la recherche
  bascule sur le plein texte français seul, qui reste opérationnel.
- Le nom du modèle est exposé, parce que changer de modèle impose de
  ré-embedder tout le corpus : les vecteurs de deux modèles différents
  vivent dans des espaces sans rapport, et la similarité devient du bruit
  sans qu'aucune erreur ne le signale.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import OrderedDict
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

FOURNISSEURS: dict[str, dict] = {
    "mistral": {
        # Endpoint européen. Sans le préfixe « eu. », les requêtes sortent
        # de l'Union.
        "url": "https://api.eu.mistral.ai/v1/embeddings",
        "modele": "mistral-embed",
        "dimensions": 1024,
        "cle": "mistral_api_key",
    },
    "openai": {
        "url": "https://api.openai.com/v1/embeddings",
        "modele": "text-embedding-3-small",
        "dimensions": 1536,
        "cle": "openai_api_key",
    },
    "local": {
        # sentence-transformers, pour une machine qui a la RAM. Utile à
        # l'ingestion hors ligne du corpus, pas en production sur 512 Mo.
        "url": "",
        "modele": "paraphrase-multilingual-MiniLM-L12-v2",
        "dimensions": 384,
        "cle": "",
    },
}

_verrou = threading.Lock()
_cache: OrderedDict[str, list[float]] = OrderedDict()
_TAILLE_CACHE = 512

_modele_local = None
_local_indisponible = False


def _config() -> Optional[dict]:
    if not settings.embeddings_enabled:
        return None
    nom = (settings.embeddings_fournisseur or "").lower()
    f = FOURNISSEURS.get(nom)
    if not f:
        return None
    if f["cle"] and not getattr(settings, f["cle"], ""):
        return None
    return {**f, "nom": nom}


def modele_actif() -> Optional[str]:
    """Identifie le modèle, pour le stocker à côté des vecteurs."""
    f = _config()
    return f"{f['nom']}:{f['modele']}" if f else None


def dimensions() -> Optional[int]:
    f = _config()
    return f["dimensions"] if f else None


def _cle_cache(texte: str) -> str:
    return hashlib.sha256(texte.strip().lower().encode()).hexdigest()


def _lire_cache(texte: str) -> Optional[list[float]]:
    cle = _cle_cache(texte)
    with _verrou:
        vecteur = _cache.get(cle)
        if vecteur is not None:
            _cache.move_to_end(cle)
        return vecteur


def _ecrire_cache(texte: str, vecteur: list[float]) -> None:
    cle = _cle_cache(texte)
    with _verrou:
        _cache[cle] = vecteur
        _cache.move_to_end(cle)
        while len(_cache) > _TAILLE_CACHE:
            _cache.popitem(last=False)


def _charger_local():
    """Charge sentence-transformers, quand la machine a la RAM pour."""
    global _modele_local, _local_indisponible
    if _modele_local is not None or _local_indisponible:
        return _modele_local
    try:
        from sentence_transformers import SentenceTransformer

        logger.info("Chargement du modèle local %s", FOURNISSEURS["local"]["modele"])
        _modele_local = SentenceTransformer(FOURNISSEURS["local"]["modele"])
        return _modele_local
    except Exception as e:  # noqa: BLE001
        logger.warning("Modèle local indisponible (%s).", e)
        _local_indisponible = True
        return None


def _appeler_api(textes: list[str], f: dict) -> Optional[list[list[float]]]:
    cle = getattr(settings, f["cle"], "")
    try:
        with httpx.Client(timeout=settings.embeddings_timeout) as client:
            reponse = client.post(
                f["url"],
                headers={
                    "Authorization": f"Bearer {cle}",
                    "Content-Type": "application/json",
                },
                json={"model": f["modele"], "input": textes},
            )
    except httpx.RequestError as e:
        logger.warning("Embeddings injoignables (%s) : repli sur le plein texte.", e)
        return None

    if reponse.status_code != 200:
        logger.warning(
            "Embeddings : %s %s — repli sur le plein texte.",
            reponse.status_code, reponse.text[:150],
        )
        return None

    try:
        donnees = sorted(reponse.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in donnees]
    except (KeyError, TypeError) as e:
        logger.warning("Réponse d'embeddings illisible (%s).", e)
        return None


def encoder(texte: str) -> Optional[list[float]]:
    """Transforme un texte en vecteur, ou None si les embeddings sont absents.

    Ne lève jamais : la recherche doit continuer en plein texte si le
    fournisseur est indisponible.
    """
    if not texte or not texte.strip():
        return None

    f = _config()
    if not f:
        return None

    en_cache = _lire_cache(texte)
    if en_cache is not None:
        return en_cache

    if f["nom"] == "local":
        modele = _charger_local()
        if modele is None:
            return None
        vecteur = modele.encode(texte, normalize_embeddings=True).tolist()
    else:
        resultat = _appeler_api([texte], f)
        if not resultat:
            return None
        vecteur = resultat[0]

    _ecrire_cache(texte, vecteur)
    return vecteur


def encoder_lot(textes: list[str]) -> list[Optional[list[float]]]:
    """Encode plusieurs textes en une passe, pour l'ingestion du corpus."""
    f = _config()
    if not f or not textes:
        return [None] * len(textes)

    if f["nom"] == "local":
        modele = _charger_local()
        if modele is None:
            return [None] * len(textes)
        return [v.tolist() for v in modele.encode(textes, normalize_embeddings=True, batch_size=32)]

    # Les API plafonnent la taille d'un lot : on découpe.
    vecteurs: list[Optional[list[float]]] = []
    for debut in range(0, len(textes), settings.embeddings_taille_lot):
        tranche = textes[debut : debut + settings.embeddings_taille_lot]
        resultat = _appeler_api(tranche, f)
        vecteurs.extend(resultat if resultat else [None] * len(tranche))
    return vecteurs


def en_pgvector(vecteur: Optional[list[float]]) -> Optional[str]:
    """Formate un vecteur pour le cast ::vector de pgvector."""
    if vecteur is None:
        return None
    return "[" + ",".join(f"{x:.6f}" for x in vecteur) + "]"


def disponible() -> bool:
    return _config() is not None


def info() -> dict:
    f = _config()
    if not f:
        return {
            "actifs": False,
            "modele": "desactives",
            "recherche": "plein texte français seul",
        }
    return {
        "actifs": True,
        "fournisseur": f["nom"],
        "modele": f["modele"],
        "dimensions": f["dimensions"],
        "hebergement": "UE" if f["nom"] == "mistral" else "hors UE",
        "cache": len(_cache),
    }
