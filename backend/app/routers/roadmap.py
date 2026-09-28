"""
routers/roadmap.py — Module 2 (payant) : parcours de mobilité.

Entonnoir : choix de la voie (public/privé) → [privé: vérif RNCP] → choix du niveau
(L1/DAP, L2-L3, Master, BTS) → paiement → roadmap (arbre + liste) avec échéances,
décompte et suivi déclaratif des étapes.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.db import get_db
from app.deps import get_current_user
from app.models import User, Piste
from app.schemas import VoieIn
from app.data.procedures.france import NIVEAUX, NIVEAUX_IDS
from app.services.roadmap_engine import build_tree, etape_par_id

router = APIRouter(prefix="/api/roadmap", tags=["roadmap"])


def _owned(db: Session, piste_id: int, user: User) -> Piste:
    p = db.get(Piste, piste_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "Piste introuvable")
    return p


def _niveau_suggere(profil: dict | None) -> str:
    """Devine le niveau (entonnoir) à partir du profil d'orientation. L'utilisateur
    peut toujours le corriger dans l'interface."""
    n = (profil or {}).get("niveau_vise", "") or (profil or {}).get("niveau", "")
    n = n.lower()
    if "master" in n or "m1" in n or "m2" in n:
        return "master"
    if "bts" in n:
        return "bts"
    if "licence" in n or "bachelor" in n or "l1" in n or "but" in n:
        return "l1_dap"
    return ""


@router.get("/niveaux")
def niveaux(piste_id: int | None = None, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    """Liste des niveaux de l'entonnoir + suggestion basée sur le profil."""
    suggere = ""
    if piste_id:
        p = db.get(Piste, piste_id)
        if p and p.user_id == user.id:
            suggere = _niveau_suggere(p.profil)
    return {"niveaux": NIVEAUX, "suggere": suggere}


@router.post("/voie")
def choisir_voie(body: VoieIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.voie not in ("public", "prive"):
        raise HTTPException(422, "voie doit être 'public' ou 'prive'")
    p = _owned(db, body.piste_id, user)
    p.voie = body.voie
    db.commit()
    return {"piste_id": p.id, "voie": p.voie,
            "rncp_requis": body.voie == "prive",
            "message": "Pour le privé, vérifie d'abord le titre RNCP." if body.voie == "prive"
                       else "Voie publique : la roadmap est standardisée."}


class GenerateIn(BaseModel):
    piste_id: int
    niveau: str | None = None      # l1_dap | l2_l3 | master | bts
    rentree: str | None = None     # date d'ancrage "YYYY-MM-DD" (défaut : prochaine rentrée)


@router.post("/generate")
def generate(body: GenerateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _owned(db, body.piste_id, user)
    if not p.paid:
        raise HTTPException(402, "Le parcours de mobilité est payant — paiement requis.")

    niveau = (body.niveau or "").strip()
    if niveau and niveau not in NIVEAUX_IDS:
        raise HTTPException(422, "niveau inconnu")
    if not niveau:
        niveau = (p.roadmap or {}).get("niveau") or _niveau_suggere(p.profil)
    anchor = body.rentree or (p.roadmap or {}).get("rentree")

    done = set((p.roadmap or {}).get("done", []))
    tree = build_tree(p.voie or "public", niveau, done, anchor, p.formation_privee)
    tree["done"] = sorted(done)
    p.roadmap = tree
    db.commit()
    return tree


class StepIn(BaseModel):
    piste_id: int
    step_id: str
    fait: bool = True


@router.post("/step")
def marquer_etape(body: StepIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _owned(db, body.piste_id, user)
    if not p.paid:
        raise HTTPException(402, "Paiement requis.")
    niveau = (p.roadmap or {}).get("niveau") or ""
    if not etape_par_id(body.step_id, niveau):
        raise HTTPException(404, "Étape inconnue")
    done = set((p.roadmap or {}).get("done", []))
    done.add(body.step_id) if body.fait else done.discard(body.step_id)
    anchor = (p.roadmap or {}).get("rentree")
    tree = build_tree(p.voie or "public", niveau, done, anchor, p.formation_privee)
    tree["done"] = sorted(done)
    p.roadmap = tree
    db.commit()
    return tree
