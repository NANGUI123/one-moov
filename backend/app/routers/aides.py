"""
routers/aides.py — Aides IA du parcours de mobilité (partie payante).

- /entretien    : simulation d'entretien Campus France (feature 10). Le LLM joue
                  l'agent d'entretien, une question à la fois, puis un bilan ([[FIN]]).
- /contestation : aide à la contestation d'un refus d'admission ou de visa (feature 11).
                  Voies réalistes + conseils + brouillon de courrier personnalisable.

Toutes deux sont ANCRÉES sur le projet de l'étudiant et honnêtes (aucune garantie
inventée). Repli « mode guidé » sans clé Groq.
"""
import re
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.models import User, Piste
from app.schemas import EntretienIn, ContestationIn
from app.services.llm import get_llm, Meter, LLMUnavailable
from app.prompts import (SYSTEM_ENTRETIEN, ENTRETIEN_OUVERTURE, ENTRETIEN_QUESTIONS_GUIDE,
                         SYSTEM_CONTESTATION, CONTESTATION_TEMPLATE)

router = APIRouter(prefix="/api/aides", tags=["aides"])
logger = logging.getLogger(__name__)


def _piste_payee(db: Session, piste_id: int, user: User) -> Piste:
    p = db.get(Piste, piste_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "Piste introuvable")
    if not p.paid:
        raise HTTPException(402, "Cette aide fait partie du parcours de mobilité (formule payante).")
    return p


def _contexte_projet(p: Piste) -> str:
    pr = p.profil or {}
    bits = []
    if pr.get("domaine"):
        bits.append(f"domaine : {pr['domaine']}")
    if pr.get("niveau_vise") or pr.get("niveau"):
        bits.append(f"niveau visé : {pr.get('niveau_vise') or pr.get('niveau')}")
    if pr.get("projet_pro") or pr.get("resume_pro"):
        bits.append(f"projet pro : {pr.get('projet_pro') or pr.get('resume_pro')}")
    fp = p.formation_privee or {}
    if fp.get("intitule"):
        bits.append(f"formation visée : {fp['intitule']}"
                    + (f" ({fp['etablissement']})" if fp.get("etablissement") else ""))
    return " ; ".join(bits) or "projet non détaillé"


# ── Simulation d'entretien Campus France ───────────────────────────
@router.post("/entretien")
def entretien(body: EntretienIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _piste_payee(db, body.piste_id, user)
    prenom = (user.prenom or "").strip() or "l'étudiant"
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]

    llm = get_llm()
    if not llm.available:
        return _entretien_guide(msgs, prenom)

    try:
        system = SYSTEM_ENTRETIEN.format(PRENOM=prenom, CONTEXTE=_contexte_projet(p))
        meter = Meter(db=db, endpoint="aides/entretien", user_id=user.id, piste_id=p.id)
        text = llm.chat(msgs or [{"role": "user", "content": "Commençons l'entretien."}],
                        system=system, max_tokens=500, temperature=0.7, meter=meter)
        return {"content": text, "mode": "IA", "fin": "[[FIN]]" in text}
    except LLMUnavailable:
        return _entretien_guide(msgs, prenom)


def _entretien_guide(msgs: list[dict], prenom: str) -> dict:
    n_rep = sum(1 for m in msgs if m["role"] == "user")
    if n_rep == 0:
        return {"content": ENTRETIEN_OUVERTURE.format(PRENOM=prenom), "mode": "guidé", "fin": False}
    if n_rep < len(ENTRETIEN_QUESTIONS_GUIDE):
        return {"content": ENTRETIEN_QUESTIONS_GUIDE[n_rep], "mode": "guidé", "fin": False}
    return {"content": "Merci pour vos réponses. Points forts : un projet exprimé et de la "
                       "motivation. À travailler : reliez chaque réponse à un objectif "
                       "professionnel précis, et documentez votre financement. Continuez à "
                       "vous entraîner à l'oral — vous progressez. [[FIN]]",
            "mode": "guidé", "fin": True}


# ── Aide à la contestation d'un refus ──────────────────────────────
@router.post("/contestation")
def contestation(body: ContestationIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _piste_payee(db, body.piste_id, user)
    contexte = {
        "type_refus": body.type_refus, "formation": body.formation,
        "etablissement": body.etablissement, "motif": body.motif,
        "arguments": body.arguments, "prenom": user.prenom or "",
    }

    llm = get_llm()
    if not llm.available:
        return {**_contestation_guide(body), "mode": "guidé"}

    try:
        meter = Meter(db=db, endpoint="aides/contestation", user_id=user.id, piste_id=p.id)
        raw = llm.chat(
            [{"role": "user", "content": CONTESTATION_TEMPLATE.format(
                contexte=json.dumps(contexte, ensure_ascii=False))}],
            system=SYSTEM_CONTESTATION, max_tokens=900, temperature=0.5,
            json_mode=True, meter=meter)
        data = json.loads(_clean_json(raw))
        return {
            "voies": data.get("voies", [])[:4],
            "conseils": data.get("conseils", [])[:5],
            "lettre": data.get("lettre", ""),
            "avertissement": data.get("avertissement",
                "Aucune issue n'est garantie ; respecte les délais indiqués dans ta notification de refus."),
            "mode": "IA",
        }
    except Exception as e:
        logger.warning(f"Contestation LLM échouée ({e}) — repli guidé")
        return {**_contestation_guide(body), "mode": "guidé"}


def _clean_json(raw: str) -> str:
    """Extrait l'objet JSON, qu'il soit brut ou entouré de balises ```json … ```."""
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()
    i, j = s.find("{"), s.rfind("}")
    return s[i:j + 1] if i >= 0 and j > i else s


def _contestation_guide(body: ContestationIn) -> dict:
    visa = body.type_refus == "visa"
    if visa:
        voies = [
            "Recours gracieux auprès du consulat qui a refusé (dans les 2 mois).",
            "Recours auprès de la Commission de recours contre les refus de visa (CRRV), à Nantes.",
            "Recours contentieux devant le tribunal administratif de Nantes en dernier ressort.",
        ]
    else:
        voies = [
            "Recours gracieux : demande polie de réexamen auprès de l'établissement.",
            "Participer à la phase complémentaire / aux vœux encore ouverts.",
            "Solliciter vos autres vœux et vérifier les places vacantes.",
        ]
    formation = body.formation or "[formation]"
    etab = body.etablissement or "[établissement]"
    lettre = (
        f"Objet : Demande de réexamen — {formation}\n\n"
        f"Madame, Monsieur,\n\n"
        f"J'ai bien reçu votre décision concernant ma candidature en {formation} "
        f"au sein de {etab}, et je vous en remercie. Je me permets de solliciter "
        f"respectueusement un réexamen de mon dossier.\n\n"
        f"[Rappelez ici votre projet, votre motivation, et tout élément nouveau ou mal pris "
        f"en compte : {body.arguments or '…'}]\n\n"
        f"Conscient(e) de la sélectivité de votre formation, je reste à votre disposition "
        f"pour tout complément d'information.\n\n"
        f"Je vous prie d'agréer, Madame, Monsieur, l'expression de ma considération distinguée.\n\n"
        f"[Prénom NOM] — [contact]"
    )
    conseils = [
        "Restez courtois et factuel : un recours gracieux se joue sur le ton et les pièces.",
        "Ajoutez tout élément NOUVEAU (résultats, attestation) non fourni initialement.",
        "Respectez scrupuleusement le délai indiqué dans votre notification de refus.",
        "Préparez en parallèle un plan B (autres vœux, phase complémentaire).",
    ]
    return {"voies": voies, "conseils": conseils, "lettre": lettre,
            "avertissement": "Aucune issue n'est garantie ; ces démarches respectent les "
                             "délais indiqués dans votre notification de refus."}
