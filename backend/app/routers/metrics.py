"""
routers/metrics.py — Tableau de bord des coûts (instruction 6).
Coût global, coût par utilisateur, et rentabilité vs prix de vente.
NB : /admin/* devra être restreint aux comptes admin en production.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.config import get_settings
from app.models import User
from app.services import token_meter

router = APIRouter(prefix="/api", tags=["coûts"])
settings = get_settings()
EUR_USD = 1.08  # taux indicatif pour convertir le prix de vente en USD


@router.get("/admin/costs")
def global_costs(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    prix_usd = settings.PRIX_PARCOURS_EUR * EUR_USD
    return {
        "global": token_meter.summary(db),
        "budget_mensuel_usd": settings.BUDGET_MENSUEL_USD,
        "cout_mois_courant_usd": round(token_meter.month_cost_usd(db), 4),
        "prix_parcours": {
            "eur": settings.PRIX_PARCOURS_EUR,
            "fcfa": settings.prix_fcfa,
        },
        "rentabilite": token_meter.rentabilite(db, prix_usd),
    }


@router.get("/me/costs")
def my_costs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return token_meter.per_user(db, user.id)
