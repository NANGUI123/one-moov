"""Routes de l'agent d'orientation."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.schemas import (
    RequeteOrientation, ReponseOrientation, RequeteRoadmap, Roadmap,
)
from app.agents.agent1 import intake, roadmap as svc_roadmap

router = APIRouter(prefix="/api/orientation", tags=["Agent 1, orientation"])


class ReponsesGuidees(BaseModel):
    """Les réponses du parcours guidé, rassemblées."""

    reponses: dict[str, str] = Field(default_factory=dict)


@router.get("/etapes-guidees")
def etapes_guidees() -> dict:
    """La liste des questions du parcours guidé.

    Le client la récupère quand il a du réseau et la garde sur l'appareil.
    C'est ce qui lui permet de poser les sept questions hors ligne, puis de
    faire valider les réponses d'un seul appel au retour de la connexion.

    La liste est publiée plutôt que recopiée dans le navigateur : si l'équipe
    ajoute une question, les clients la voient à leur prochaine connexion sans
    attendre un déploiement du front.
    """
    return {"etapes": intake.ETAPES_GUIDEES}


@router.post("/profil-guide", response_model=ReponseOrientation)
def profil_guide(corps: ReponsesGuidees) -> ReponseOrientation:
    """Valide en un appel les réponses saisies hors ligne."""
    return intake.intake_guide_lot(corps.reponses)


@router.post("/conversation", response_model=ReponseOrientation)
def conversation(requete: RequeteOrientation) -> ReponseOrientation:
    """Récit de l'étudiant vers profil structuré.

    Ne touche pas à la base : l'intake ne travaille que sur ce que le
    navigateur envoie, et ne conserve rien.
    """
    try:
        return intake.traiter(requete)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Orientation indisponible : {e}") from e


@router.post("/roadmap", response_model=Roadmap)
def generer_roadmap(requete: RequeteRoadmap, db: Session = Depends(get_db)) -> Roadmap:
    """Profil vers feuille de route.

    Croise la base d'établissements, les faits vérifiés et le RAG.
    """
    if not requete.profil.domaine:
        raise HTTPException(
            status_code=422,
            detail="Le profil est incomplet : le domaine d'études est nécessaire.",
        )
    try:
        return svc_roadmap.generer(db, requete.profil, requete.secteurs)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Génération impossible : {e}") from e
