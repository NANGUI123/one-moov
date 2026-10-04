"""Quotas d'appels au modèle, comptés en base.

Pourquoi en base et pas en mémoire
----------------------------------
Un compteur en mémoire est plus simple à écrire et faux dès le deuxième
processus : chaque instance a le sien, et la limite effective est multipliée
par leur nombre. Un service déployé derrière un répartiteur de charge ne
peut pas tenir une limite de cette façon, et il faudrait l'écrire dans la
documentation comme une réserve.

La table `token_usage` enregistre déjà une ligne par appel, avec son
utilisateur et son horodatage. Compter ces lignes coûte une requête indexée
et donne une limite juste quel que soit le nombre d'instances. Le travail
était déjà fait, il n'était pas branché.

Ce que le quota protège
-----------------------
Pas la marge : l'intelligence artificielle pèse 1,4 % du coût variable d'un
étudiant payant. Il protège contre l'usage automatisé de la partie gratuite,
qui est ouverte sans compte et où rien n'oblige à être un étudiant.

Le garde-fou budgétaire mensuel est traité ici aussi, parce qu'il relève de
la même question : une dépense qu'on surveille sans pouvoir l'arrêter n'est
pas surveillée.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import TokenUsage

logger = logging.getLogger(__name__)
settings = get_settings()


def _debut_de_journee() -> datetime:
    """Minuit UTC. Une fenêtre glissante de 24 h serait plus juste mais
    moins compréhensible : un étudiant bloqué veut savoir quand ça repart,
    et « demain » est une réponse qu'on peut donner."""
    maintenant = datetime.now(timezone.utc)
    return maintenant.replace(hour=0, minute=0, second=0, microsecond=0)


def appels_du_jour(db: Session, user_id: int | None) -> int:
    """Nombre d'appels au modèle imputés à cet utilisateur depuis minuit."""
    if user_id is None:
        return 0
    return int(
        db.query(func.count(TokenUsage.id))
        .filter(TokenUsage.user_id == user_id,
                TokenUsage.created_at >= _debut_de_journee())
        .scalar() or 0
    )


def limite_quotidienne() -> int:
    return int(settings.QUOTA_MESSAGES_GRATUIT_JOUR)


def etat(db: Session, user_id: int | None) -> dict:
    """De quoi afficher « il te reste N échanges aujourd'hui »."""
    limite = limite_quotidienne()
    utilises = appels_du_jour(db, user_id)
    return {
        "limite": limite,
        "utilises": utilises,
        "restants": max(0, limite - utilises),
        "atteint": utilises >= limite,
    }


def depasse(db: Session, user_id: int | None) -> bool:
    """Vrai si cet utilisateur a consommé son quota du jour.

    Un visiteur sans compte n'est pas compté : il n'y a rien à quoi
    rattacher ses appels. C'est une limite connue, et la parade n'est pas un
    quota mais l'obligation de compte, qui existe déjà sur les fonctions
    coûteuses.
    """
    if user_id is None:
        return False
    return appels_du_jour(db, user_id) >= limite_quotidienne()


def budget_mensuel_depasse(db: Session) -> bool:
    """Vrai si la dépense des 30 derniers jours atteint le plafond configuré.

    Un plafond à zéro signifie « pas de plafond » : c'est la valeur par
    défaut, et refuser tous les appels dans ce cas serait une panne déguisée
    en garde-fou.
    """
    plafond = float(getattr(settings, "BUDGET_MENSUEL_USD", 0) or 0)
    if plafond <= 0:
        return False
    depuis = datetime.now(timezone.utc) - timedelta(days=30)
    depense = float(
        db.query(func.coalesce(func.sum(TokenUsage.cost_usd), 0.0))
        .filter(TokenUsage.created_at >= depuis).scalar() or 0.0
    )
    if depense >= plafond:
        logger.error("Budget mensuel atteint : %.2f / %.2f USD — bascule en "
                     "mode guidé pour tout le monde.", depense, plafond)
        return True
    return False


def doit_basculer_en_guide(db: Session, user_id: int | None) -> str | None:
    """Raison de refuser l'IA à cet appel, ou None si tout va bien.

    La chaîne renvoyée est destinée à l'étudiant : elle dit ce qui se passe
    et quand ça repart, plutôt que « quota dépassé ».
    """
    if budget_mensuel_depasse(db):
        return ("Le service tourne en mode guidé pour aujourd'hui. Ta feuille "
                "de route et tes étapes restent complètes.")
    if depasse(db, user_id):
        limite = limite_quotidienne()
        return (f"Tu as utilisé tes {limite} échanges avec l'assistant pour "
                f"aujourd'hui. Ils repartent demain. En attendant, les "
                f"conseils de chaque étape et leurs sources officielles "
                f"restent accessibles.")
    return None
