"""
routers/pistes.py — Un compte peut ouvrir plusieurs pistes (une par projet/pays).
Le tableau de bord (feature 14) liste toutes les pistes avec leur avancement.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.db import get_db
from app.deps import get_current_user
from app.models import User, Piste

router = APIRouter(prefix="/api/pistes", tags=["pistes"])


class PisteIn(BaseModel):
    pays: str = "Cameroun"


@router.post("")
def creer_piste(body: PisteIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = Piste(user_id=user.id, pays=body.pays)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _piste_dict(p)


@router.get("")
def lister_pistes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Tableau de bord : toutes les pistes de l'utilisateur, avec un résumé d'avancement."""
    pistes = (db.query(Piste).filter(Piste.user_id == user.id)
              .order_by(Piste.created_at.desc()).all())
    return {"pistes": [_resume(p) for p in pistes], "total": len(pistes)}


@router.get("/{piste_id}")
def get_piste(piste_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(Piste, piste_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "Piste introuvable")
    return _piste_dict(p)


def _etape_courante(p: Piste) -> str:
    if p.paid:
        return "roadmap"
    if p.voie:
        return "parcours"
    if p.formations:
        return "formations"
    return "orientation"


def _resume(p: Piste) -> dict:
    """Ligne compacte pour le tableau de bord."""
    rm = p.roadmap or {}
    pr = p.profil or {}
    prochaine = rm.get("prochaine_action") or {}
    titre = ((pr.get("domaine") or "") + (f" · {pr.get('niveau_vise')}" if pr.get("niveau_vise") else "")).strip(" ·")
    return {
        "id": p.id,
        "pays": p.pays,
        "titre": titre or "Nouvelle piste",
        "voie": p.voie,
        "paid": p.paid,
        "etape": _etape_courante(p),
        "progression_pct": rm.get("progression_pct", 0),
        "nb_formations": len(p.formations or []),
        "nb_en_retard": rm.get("nb_en_retard", 0),
        "prochaine_action": prochaine.get("label", ""),
        "prochaine_echeance": prochaine.get("echeance_str", ""),
    }


def _piste_dict(p: Piste) -> dict:
    return {"id": p.id, "pays": p.pays, "voie": p.voie, "profil": p.profil,
            "formations": p.formations, "formation_privee": p.formation_privee,
            "rncp": p.rncp, "roadmap": p.roadmap, "paid": p.paid}
