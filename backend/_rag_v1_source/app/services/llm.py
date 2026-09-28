"""Orchestrateur de modèle de langage.

Trois niveaux, dans cet ordre, exactement comme le schéma d'architecture :

    1. Primaire        le fournisseur principal (Hugging Face par défaut)
    2. Secours         bascule automatique si le primaire échoue
    3. Mode guidé      aucune IA, chemin déterministe dans les agents

La bascule est automatique et invisible pour l'étudiant. Elle est en
revanche comptée et exposée dans les métriques : c'est ce qui permet de
montrer que la résilience fonctionne vraiment, plutôt que de l'affirmer.

Ce que l'orchestrateur ne fait pas : décider d'un fait. Il met en forme,
reformule, dialogue. Les montants, délais et seuils viennent des tables
vérifiées, jamais d'ici.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

from app.config import settings
from app.services.metriques import compteurs

logger = logging.getLogger(__name__)

FOURNISSEURS: dict[str, dict[str, str]] = {
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "modele": "gemini-3.8-flash",
        "cle": "gemini_api_key",
    },
    "huggingface": {
        # Routeur d'inférence, interface compatible OpenAI. Il relaie vers
        # d'autres hébergeurs plutôt que de servir lui-même, ce qui en fait
        # une roue de secours commode : une seule clé ouvre plusieurs
        # fournisseurs.
        #
        # À NE PAS METTRE EN PRIMAIRE. Le palier gratuit n'est plus un quota
        # de requêtes mais un crédit de 0,10 $ par mois, partagé avec tout le
        # reste du compte. Quelques dizaines de feuilles de route l'épuisent,
        # et l'API répond alors 402 — une erreur qu'on lit comme une panne
        # alors que c'est une facture.
        "url": "https://router.huggingface.co/v1/chat/completions",
        "modele": "meta-llama/Llama-3.3-70B-Instruct",
        "cle": "huggingface_api_key",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        # Et non llama-3.3-70b-versatile, qui a quitté le palier gratuit de
        # Groq le 16 août 2026 pour devenir réservé aux comptes entreprise.
        # Une clé gratuite posée sur l'ancien nom fait répondre l'API en
        # erreur, l'orchestrateur bascule sur le secours, et on croit à une
        # panne de fournisseur alors que c'est un nom de modèle périmé.
        #
        # Le palier gratuit plafonne à 30 requêtes par minute, 1 000 par jour
        # et 8 000 jetons par minute. C'est la raison pour laquelle la
        # génération de feuille de route, de loin le plus gros appel, est
        # dirigée vers Mistral : elle épuiserait ce budget de jetons à elle
        # seule.
        "modele": "openai/gpt-oss-120b",
        "cle": "groq_api_key",
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "modele": "gpt-4o-mini",
        "cle": "openai_api_key",
    },
    "mistral": {
        "url": "https://api.mistral.ai/v1/chat/completions",
        "modele": "mistral-large-latest",
        "cle": "mistral_api_key",
    },
    "ollama": {
        "url": "http://localhost:11434/v1/chat/completions",
        "modele": "llama3.2",
        "cle": "",
    },
}


class ErreurLLM(Exception):
    """Aucun niveau d'IA n'a pu répondre."""


class ModeMock(Exception):
    """Signale à l'appelant de basculer sur le mode guidé, sans IA."""


# Les trois usages du modèle. Chacun peut avoir son fournisseur et son
# modèle ; à défaut, il suit le réglage global. Le niveau de secours, lui,
# reste commun : une panne de fournisseur ignore nos découpages.
FONCTIONS = ("orientation", "roadmap", "chatbot")


def _reglage(fonction: str | None) -> tuple[str, str]:
    """Le fournisseur et le modèle du primaire, pour cette fonction."""
    if fonction in FONCTIONS:
        fournisseur = getattr(settings, f"llm_provider_{fonction}", "") or ""
        modele = getattr(settings, f"llm_modele_{fonction}", "") or ""
        if fournisseur.strip():
            # Un fournisseur propre à la fonction emporte son modèle avec lui,
            # ou celui du fournisseur par défaut. Il ne récupère surtout pas
            # llm_model, qui décrit un modèle d'un autre hôte.
            return fournisseur, modele
        if modele.strip():
            return settings.llm_provider, modele

    return settings.llm_provider, settings.llm_model


def _resoudre(nom: str, modele_voulu: str = "") -> tuple[str, str, str, str] | None:
    """Renvoie (nom, url, modèle, clé) si le fournisseur est utilisable."""
    nom = (nom or "").strip().lower()
    if not nom or nom == "mock":
        return None

    f = FOURNISSEURS.get(nom)
    if not f:
        logger.warning("Fournisseur inconnu, ignoré : %s", nom)
        return None

    cle = getattr(settings, f["cle"], "") if f["cle"] else "ollama-local"
    if not cle:
        return None

    return nom, f["url"], (modele_voulu or "").strip() or f["modele"], cle


def niveaux(fonction: str | None = None) -> list[tuple[str, str, str, str]]:
    """Les fournisseurs réellement utilisables, du primaire au secours."""
    primaire, modele = _reglage(fonction)

    retenus, vus = [], set()
    # Le modèle demandé ne s'applique qu'au primaire : le secours garde le
    # sien, sinon on lui réclamerait un modèle qu'il n'héberge pas.
    for nom, voulu in ((primaire, modele), (settings.llm_provider_secours, "")):
        resolu = _resoudre(nom, voulu)
        if resolu and resolu[0] not in vus:
            vus.add(resolu[0])
            retenus.append(resolu)
    return retenus


def _appeler(
    cible: tuple[str, str, str, str],
    systeme: str,
    utilisateur: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    nom, url, modele, cle = cible

    entetes = {"Content-Type": "application/json"}
    if nom != "ollama":
        entetes["Authorization"] = f"Bearer {cle}"

    charge = {
        "model": modele,
        "messages": [
            {"role": "system", "content": systeme},
            {"role": "user", "content": utilisateur},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    try:
        with httpx.Client(timeout=settings.llm_timeout) as client:
            reponse = client.post(url, headers=entetes, json=charge)
    except httpx.RequestError as e:
        raise ErreurLLM(f"{nom} injoignable : {e}") from e

    if reponse.status_code != 200:
        # Trois codes veulent dire tout autre chose qu'une panne, et les
        # confondre coûte une soirée de diagnostic. On les nomme.
        motifs = {
            402: "crédit épuisé chez le fournisseur — c'est une facture, pas une panne",
            404: "modèle introuvable : le nom a peut-être quitté le palier "
                 "gratuit (python -m scripts.verifier_cles le dira)",
            429: "quota atteint : trop de requêtes ou de jetons sur la fenêtre courante",
        }
        motif = motifs.get(reponse.status_code)
        detail = motif or reponse.text[:200]
        raise ErreurLLM(f"{nom} a répondu {reponse.status_code} : {detail}")

    try:
        contenu = reponse.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise ErreurLLM(f"Réponse de {nom} illisible") from e

    return parser_json(contenu)


def chat_json(
    systeme: str,
    utilisateur: str,
    temperature: float = 0.3,
    max_tokens: int = 1600,
    fonction: str | None = None,
) -> dict[str, Any]:
    """Interroge le modèle, en basculant sur le secours si le primaire échoue.

    « fonction » vaut « orientation », « roadmap » ou « chatbot » et choisit
    le fournisseur primaire quand un réglage propre existe. Sans elle, c'est
    le réglage global qui s'applique.

    Lève ModeMock quand aucun niveau d'IA n'est disponible : l'agent
    appelant a dans ce cas un chemin déterministe qui produit une réponse
    correcte, simplement moins fluide.
    """
    cibles = niveaux(fonction)
    if not cibles:
        raise ModeMock()

    dernier: Exception | None = None

    for rang, cible in enumerate(cibles):
        nom = cible[0]
        debut = time.monotonic()
        try:
            resultat = _appeler(cible, systeme, utilisateur, temperature, max_tokens)
        except ErreurLLM as e:
            dernier = e
            compteurs.incrementer(f"llm.echec.{nom}")
            logger.warning("Niveau %d (%s) a échoué : %s", rang + 1, nom, e)
            continue

        compteurs.incrementer(f"llm.succes.{nom}")
        compteurs.observer("llm.duree_ms", (time.monotonic() - debut) * 1000)
        if rang > 0:
            compteurs.incrementer("llm.bascule_secours")
            logger.info("Servi par le niveau de secours (%s)", nom)
        return resultat

    compteurs.incrementer("llm.mode_guide")
    logger.error("Tous les niveaux d'IA ont échoué, passage en mode guidé.")
    raise ModeMock() from dernier


def parser_json(brut: str) -> dict[str, Any]:
    """Parse la sortie du modèle en tolérant les clôtures Markdown.

    Un modèle renvoie parfois ```json ... ``` malgré la consigne, ou du
    texte autour de l'objet. On récupère ce qui est exploitable plutôt que
    d'échouer sur un détail de mise en forme.
    """
    nettoye = re.sub(r"^\s*```(?:json)?", "", brut.strip())
    nettoye = re.sub(r"```\s*$", "", nettoye).strip()

    try:
        return json.loads(nettoye)
    except json.JSONDecodeError:
        debut, fin = nettoye.find("{"), nettoye.rfind("}")
        if debut != -1 and fin > debut:
            try:
                return json.loads(nettoye[debut : fin + 1])
            except json.JSONDecodeError:
                pass
    raise ErreurLLM("Le modèle n'a pas renvoyé de JSON exploitable")


def info_fournisseur() -> dict[str, Any]:
    """État de l'orchestrateur, sans jamais exposer une clé."""
    cibles = niveaux()
    if not cibles:
        return {
            "fournisseur": "aucun",
            "modele": "non configuré",
            "configure": False,
            "orchestrateur": [
                {"niveau": 1, "role": "primaire", "fournisseur": settings.llm_provider or "aucun", "pret": False},
                {"niveau": 2, "role": "secours", "fournisseur": settings.llm_provider_secours or "aucun", "pret": False},
                {"niveau": 3, "role": "mode guidé", "fournisseur": "sans IA", "pret": True},
            ],
            "message": "Aucune clé de fournisseur IA n'est configurée : l'application utilise les chemins de secours déterministes.",
            "par_fonction": par_fonction(),
        }

    detail = [
        {
            "niveau": i + 1,
            "role": "primaire" if i == 0 else "secours",
            "fournisseur": nom,
            "modele": modele,
            "pret": True,
        }
        for i, (nom, _url, modele, _cle) in enumerate(cibles)
    ]
    detail.append(
        {"niveau": len(detail) + 1, "role": "mode guidé", "fournisseur": "sans IA", "pret": True}
    )

    primaire = cibles[0]
    return {
        "fournisseur": primaire[0],
        "modele": primaire[2],
        "configure": True,
        "orchestrateur": detail,
        "par_fonction": par_fonction(),
    }


def par_fonction() -> dict[str, dict]:
    """Quel modèle sert quoi, en une lecture.

    Utile au diagnostic autant qu'à la soutenance : « quel fournisseur génère
    la feuille de route ? » se répond en interrogeant l'application plutôt
    qu'en relisant la configuration, où une variable mal nommée passe
    inaperçue.
    """
    resume = {}
    for fonction in FONCTIONS:
        cibles = niveaux(fonction)
        resume[fonction] = {
            "fournisseur": cibles[0][0] if cibles else "mode guidé",
            "modele": cibles[0][2] if cibles else "sans IA",
            "secours": cibles[1][0] if len(cibles) > 1 else "aucun",
        }
    # L'orientation guidée est le seul chemin qui ne consulte aucun modèle,
    # et c'est ce qui la rend jouable hors ligne.
    resume["orientation"]["mode_guide_sans_modele"] = True
    return resume
