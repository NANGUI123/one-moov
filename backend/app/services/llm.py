"""
services/llm.py — Client LLM Groq uniquement, avec cascade de modèles.

- Essaie les modèles Groq dans l'ordre (principal → secours), tous chez Groq.
- Compte les tokens et enregistre le coût (token_meter) à chaque appel.
- Si aucune clé : lève LLMUnavailable → l'appelant bascule en « mode guidé » sans IA.
- Frugalité : `leger=True` force le petit modèle pour les tâches simples.
"""
import logging
from dataclasses import dataclass
from openai import OpenAI
from sqlalchemy.orm import Session
from app.config import get_settings
from app.services import token_meter

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class Meter:
    db: Session
    endpoint: str
    user_id: int | None = None
    piste_id: int | None = None


class GroqLLM:
    def __init__(self):
        self._client = None
        if settings.GROQ_API_KEY:
            self._client = OpenAI(api_key=settings.GROQ_API_KEY,
                                  base_url="https://api.groq.com/openai/v1")
        self.models = settings.groq_models
        self.model_leger = settings.GROQ_MODEL_LEGER

    @property
    def available(self) -> bool:
        return self._client is not None

    def chat(self, messages: list[dict], *, system: str | None = None,
             max_tokens: int = 800, temperature: float = 0.7,
             json_mode: bool = False, leger: bool = False,
             meter: Meter | None = None) -> str:
        if not self._client:
            raise LLMUnavailable("GROQ_API_KEY absente — bascule en mode guidé")

        full = ([{"role": "system", "content": system}] if system else []) + messages
        kwargs = dict(messages=full, max_tokens=max_tokens, temperature=temperature)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        order = [self.model_leger] if leger else self.models
        last_err = None
        for model in order:
            try:
                resp = self._client.chat.completions.create(model=model, **kwargs)
                if meter is not None and getattr(resp, "usage", None):
                    token_meter.record(
                        meter.db, endpoint=meter.endpoint, model=model,
                        prompt_tokens=resp.usage.prompt_tokens,
                        completion_tokens=resp.usage.completion_tokens,
                        user_id=meter.user_id, piste_id=meter.piste_id,
                    )
                return resp.choices[0].message.content or ""
            except Exception as e:                       # rate-limit, panne modèle…
                last_err = e
                logger.warning(f"Groq modèle {model} en échec ({e}) — modèle suivant")
        raise LLMUnavailable(f"Tous les modèles Groq ont échoué : {last_err}")


_llm: GroqLLM | None = None


def get_llm() -> GroqLLM:
    global _llm
    if _llm is None:
        _llm = GroqLLM()
    return _llm
