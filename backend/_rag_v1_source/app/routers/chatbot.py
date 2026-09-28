"""Routes du chatbot et de la simulation d'entretien.

Le chatbot est l'offre prémium, débloquée après la génération de la feuille
de route. Il répond aux questions de procédure en citant ses sources, et
entraîne à l'entretien.

Ses échanges ne sont jamais enregistrés, même pour un compte connecté :
l'historique est envoyé par le navigateur à chaque tour et repart avec la
réponse. Une conversation en dit beaucoup plus long sur quelqu'un qu'une
liste de champs de profil.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.schemas import (
    RequeteCoach, ReponseCoach,
    RequeteQuestion, ReponseQuestion,
    RequeteEvaluation, ReponseEvaluation,
)
from app.agents.agent2 import chatbot as svc_chatbot
from app.agents.agent2 import entretien as svc_entretien

router = APIRouter(prefix="/api/chatbot", tags=["Agent 2, chatbot prémium"])


@router.post("/conversation", response_model=ReponseCoach)
def conversation(requete: RequeteCoach, db: Session = Depends(get_db)) -> ReponseCoach:
    """Question de l'étudiant vers réponse sourcée."""
    try:
        return svc_chatbot.repondre(db, requete)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Chatbot indisponible : {e}") from e


@router.post("/entretien/question", response_model=ReponseQuestion)
def question(requete: RequeteQuestion, db: Session = Depends(get_db)) -> ReponseQuestion:
    """Le jury pose la question suivante."""
    try:
        return svc_entretien.poser_question(db, requete)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Simulation indisponible : {e}") from e


@router.post("/entretien/evaluation", response_model=ReponseEvaluation)
def evaluation(requete: RequeteEvaluation) -> ReponseEvaluation:
    """Le correcteur note la réponse, sur un seul critère."""
    try:
        return svc_entretien.evaluer(requete)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Évaluation impossible : {e}") from e


@router.get("/entretien/grille")
def grille() -> dict:
    """La grille d'évaluation, pour affichage."""
    return {"criteres": svc_entretien.grille()}
