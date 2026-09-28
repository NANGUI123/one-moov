"""
services/token_meter.py — Pilotage des tokens et des coûts (instruction 6).

- Grille de prix par modèle Groq (configurable ; USD / 1M tokens).
- Enregistrement d'un TokenUsage par appel LLM.
- Agrégations : coût global, coût par utilisateur, coût par parcours.
- Garde-fous : budget mensuel, coût moyen par utilisateur vs prix de vente.

Les prix par défaut sont indicatifs (Groq, à revérifier) et se règlent ici.
"""
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models import TokenUsage

# USD par 1 000 000 de tokens (entrée, sortie). À ajuster selon la grille Groq du moment.
PRICING: dict[str, tuple[float, float]] = {
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant":    (0.05, 0.08),
    "llama-3.1-70b-versatile": (0.59, 0.79),
    "mixtral-8x7b-32768":      (0.24, 0.24),
    "gemma2-9b-it":            (0.20, 0.20),
}
_DEFAULT_PRICE = (0.59, 0.79)  # fallback conservateur


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pin, pout = PRICING.get(model, _DEFAULT_PRICE)
    return (prompt_tokens * pin + completion_tokens * pout) / 1_000_000


def record(db: Session, *, endpoint: str, model: str, prompt_tokens: int,
           completion_tokens: int, user_id: int | None = None,
           piste_id: int | None = None) -> TokenUsage:
    total = (prompt_tokens or 0) + (completion_tokens or 0)
    row = TokenUsage(
        user_id=user_id, piste_id=piste_id, endpoint=endpoint, model=model,
        prompt_tokens=prompt_tokens or 0, completion_tokens=completion_tokens or 0,
        total_tokens=total, cost_usd=cost_usd(model, prompt_tokens or 0, completion_tokens or 0),
    )
    db.add(row)
    db.commit()
    return row


# ── Agrégations (tableau de bord coûts) ────────────────────────────

def summary(db: Session) -> dict:
    tot = db.query(
        func.coalesce(func.sum(TokenUsage.total_tokens), 0),
        func.coalesce(func.sum(TokenUsage.cost_usd), 0.0),
        func.count(TokenUsage.id),
    ).one()
    n_users = db.query(func.count(func.distinct(TokenUsage.user_id))).scalar() or 0
    cost = float(tot[1])
    return {
        "tokens_total": int(tot[0]),
        "cout_total_usd": round(cost, 4),
        "appels_llm": int(tot[2]),
        "utilisateurs": int(n_users),
        "cout_moyen_par_utilisateur_usd": round(cost / n_users, 4) if n_users else 0.0,
    }


def per_user(db: Session, user_id: int) -> dict:
    tot = db.query(
        func.coalesce(func.sum(TokenUsage.total_tokens), 0),
        func.coalesce(func.sum(TokenUsage.cost_usd), 0.0),
        func.count(TokenUsage.id),
    ).filter(TokenUsage.user_id == user_id).one()
    return {
        "user_id": user_id,
        "tokens_total": int(tot[0]),
        "cout_total_usd": round(float(tot[1]), 4),
        "appels_llm": int(tot[2]),
    }


def month_cost_usd(db: Session) -> float:
    since = datetime.utcnow() - timedelta(days=30)
    v = db.query(func.coalesce(func.sum(TokenUsage.cost_usd), 0.0)) \
          .filter(TokenUsage.created_at >= since).scalar()
    return float(v or 0.0)


def budget_depasse(db: Session, budget_usd: float) -> bool:
    return month_cost_usd(db) >= budget_usd


def rentabilite(db: Session, prix_vente_usd: float) -> dict:
    """Compare le coût moyen IA par utilisateur au prix de vente (marge)."""
    s = summary(db)
    cmu = s["cout_moyen_par_utilisateur_usd"]
    return {
        "cout_moyen_ia_par_utilisateur_usd": cmu,
        "prix_vente_usd": round(prix_vente_usd, 2),
        "marge_brute_ia_usd": round(prix_vente_usd - cmu, 2),
        "part_cout_ia_pct": round(100 * cmu / prix_vente_usd, 2) if prix_vente_usd else 0.0,
    }
