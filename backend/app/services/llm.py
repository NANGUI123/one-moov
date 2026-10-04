"""
services/llm.py — Appel au modèle, avec trois niveaux de repli.

  Niveau 1  les modèles du fournisseur nominal, essayés dans l'ordre.
  Niveau 2  un fournisseur de secours chez un hébergeur DIFFÉRENT.
  Niveau 3  le mode guidé, sans IA, servi par les appelants quand ce module
            lève LLMUnavailable.

Pourquoi le secours doit être ailleurs
--------------------------------------
Une cascade de deux modèles chez le même hébergeur ne couvre qu'une panne de
modèle : retrait du catalogue, quota atteint, surcharge ponctuelle. Elle ne
couvre pas la panne de l'hébergeur, qui emporte les deux d'un coup. Le 16
août 2026, le modèle que nous avions en tête a quitté le palier gratuit de
son fournisseur ; c'était une panne de modèle, et la cascade a suffi. Une
panne d'hébergeur ne nous aurait laissé que le mode guidé.

Le niveau 2 s'active dès qu'une clé est posée et reste invisible sinon. Un
fournisseur sans clé n'est pas une erreur de configuration, c'est un niveau
de repli en moins, et l'état du service le dit.

Frugalité : `leger=True` force le petit modèle pour les tâches simples. Le
coût n'est pas l'enjeu — il pèse 1,4 % du coût variable — la latence et la
marge sous les limites de débit le sont.
"""
import logging
from dataclasses import dataclass
from openai import OpenAI
from sqlalchemy.orm import Session
from app.config import get_settings
from app.services import token_meter

logger = logging.getLogger(__name__)
settings = get_settings()

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class Meter:
    db: Session
    endpoint: str
    user_id: int | None = None
    piste_id: int | None = None


@dataclass(frozen=True)
class Niveau:
    """Un couple hébergeur + modèle, essayé dans l'ordre de la cascade."""

    hebergeur: str
    modele: str
    client: OpenAI


class CascadeLLM:
    """Essaie les niveaux dans l'ordre et s'arrête au premier qui répond."""

    def __init__(self) -> None:
        self._principal = (
            OpenAI(api_key=settings.GROQ_API_KEY, base_url=GROQ_BASE_URL)
            if settings.GROQ_API_KEY else None
        )
        self._secours = (
            OpenAI(api_key=settings.SECOURS_API_KEY,
                   base_url=settings.SECOURS_BASE_URL)
            if settings.SECOURS_API_KEY else None
        )
        self.models = settings.groq_models
        self.models_secours = settings.secours_models if self._secours else []
        self.model_leger = settings.GROQ_MODEL_LEGER

    # ------------------------------------------------------------- état

    @property
    def available(self) -> bool:
        """Au moins un niveau avec IA est joignable."""
        return bool(self._principal or self._secours)

    @property
    def secours_actif(self) -> bool:
        return self._secours is not None

    def etat(self) -> dict:
        """De quoi afficher honnêtement le niveau de résilience réel."""
        return {
            "principal": {"hebergeur": "groq", "modeles": self.models,
                          "actif": self._principal is not None},
            "secours": {"hebergeur": settings.SECOURS_BASE_URL,
                        "modeles": self.models_secours,
                        "actif": self._secours is not None},
            "mode_guide": True,
            "niveaux_avec_ia": int(self._principal is not None)
                               + int(self._secours is not None),
        }

    # ------------------------------------------------------------- appel

    def _cascade(self, leger: bool) -> list[Niveau]:
        niveaux: list[Niveau] = []
        if self._principal:
            modeles = [self.model_leger] if leger else self.models
            niveaux += [Niveau("groq", m, self._principal) for m in modeles]
        if self._secours:
            niveaux += [Niveau("secours", m, self._secours)
                        for m in self.models_secours]
        return niveaux

    def chat(self, messages: list[dict], *, system: str | None = None,
             max_tokens: int = 800, temperature: float = 0.7,
             json_mode: bool = False, leger: bool = False,
             meter: Meter | None = None) -> str:
        niveaux = self._cascade(leger)
        if not niveaux:
            raise LLMUnavailable("Aucune clé de modèle — bascule en mode guidé")

        full = ([{"role": "system", "content": system}] if system else []) + messages
        kwargs = dict(messages=full, max_tokens=max_tokens, temperature=temperature)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        derniere_erreur = None
        for niveau in niveaux:
            try:
                resp = niveau.client.chat.completions.create(
                    model=niveau.modele, **kwargs)
                if meter is not None and getattr(resp, "usage", None):
                    token_meter.record(
                        meter.db, endpoint=meter.endpoint, model=niveau.modele,
                        prompt_tokens=resp.usage.prompt_tokens,
                        completion_tokens=resp.usage.completion_tokens,
                        user_id=meter.user_id, piste_id=meter.piste_id,
                    )
                if niveau.hebergeur == "secours":
                    logger.warning(
                        "Réponse servie par le secours (%s) : le fournisseur "
                        "nominal n'a pas répondu.", niveau.modele)
                return resp.choices[0].message.content or ""
            except Exception as e:                 # quota, retrait, panne…
                derniere_erreur = e
                logger.warning("%s/%s en échec (%s) — niveau suivant",
                               niveau.hebergeur, niveau.modele, e)
        raise LLMUnavailable(f"Tous les niveaux ont échoué : {derniere_erreur}")


# Conservé pour les appelants et les tests qui nomment l'ancienne classe.
GroqLLM = CascadeLLM

_llm: CascadeLLM | None = None


def get_llm() -> CascadeLLM:
    global _llm
    if _llm is None:
        _llm = CascadeLLM()
    return _llm


def reinitialiser() -> None:
    """Oublie l'instance mémorisée. Sert aux tests qui changent la config."""
    global _llm
    _llm = None
