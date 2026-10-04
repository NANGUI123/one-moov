"""
routers/orientation.py — Module 1 (gratuit) : conseiller d'orientation + 10 formations.

- /chat       : entretien abouti (projet académique + professionnel), personnalisé au
                prénom, avec réponses au choix ([CHOICES]) ET champ libre. Se conclut
                par le marqueur [[PRET]]. Mode guidé déterministe si pas de clé Groq.
- /formations : à la clôture, on EXTRAIT le profil de la conversation puis on produit
                les 10 formations depuis la BASE (scoring déterministe — jamais inventées).
"""
import re
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user_optional
from app.models import User, Piste
from app.schemas import ChatIn, FormationsIn
from app.services.llm import get_llm, Meter, LLMUnavailable
from app.services import quotas
from app.services.orientation_engine import top_formations, domaines_couverts
from app.services import rag
from app.data.ingestion.onisep import charger_formations
from app.prompts import (SYSTEM_ORIENTATION, SYSTEM_EXTRACT, EXTRACT_TEMPLATE, GUIDE_ETAPES,
                         SYSTEM_RAPPORT, RAPPORT_TEMPLATE)

router = APIRouter(prefix="/api/orientation", tags=["orientation"])
logger = logging.getLogger(__name__)

# Transparence (feature 2) : comment les pistes sont trouvées — texte FIXE et vérifiable.
TRANSPARENCE = {
    "titre": "Comment ces pistes sont trouvées",
    "principe": "Les formations viennent de notre base vérifiée — jamais inventées par l'IA. "
                "Le classement suit des règles explicites que voici :",
    "etapes": [
        "Nous lisons votre profil (domaine, niveau visé, budget, ville, projet pro) issu de l'entretien.",
        "Nous interrogeons notre base de formations alimentée par l'open data public "
        "(ONISEP / Mon Master / Parcoursup).",
        "Un score déterministe et explicable classe chaque formation : "
        "domaine (40 pts), niveau visé (25), budget (20), ville (12), voie (6).",
        "L'IA ne choisit ni n'invente aucune école : elle ne fait que présenter le résultat. "
        "Chaque piste indique pourquoi elle vous est proposée.",
    ],
    "source": "base vérifiée (scoring déterministe) · France Compétences pour le RNCP",
}


@router.post("/chat")
def chat(body: ChatIn, db: Session = Depends(get_db),
         user: User | None = Depends(get_current_user_optional)):
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    llm = get_llm()
    # `mode` explicite depuis le front. Vide → bascule automatique
    # (libre si LLM dispo, guidée sinon).
    mode = (body.mode or "").lower().strip()
    if mode == "guidee" or (mode != "libre" and not llm.available):
        return _mode_guide(msgs)
    if not llm.available:
        return _mode_guide(msgs)
    # Quota journalier et plafond de dépense, comptés en base. Le refus sert
    # le parcours guidé plutôt qu'une erreur : l'étudiant continue.
    if user and quotas.doit_basculer_en_guide(db, user.id):
        return _mode_guide(msgs)

    prenom = (user.prenom if user else "") or "l'étudiant"

    # RAG : à partir du dernier message de l'étudiant, cherche des passages
    # pertinents (procédures ONISEP, notes d'orientation) qu'on injecte
    # comme contexte de fond. Le conseiller ne dévoile pas les passages :
    # il s'en sert pour ancrer ses conseils dans du réel.
    dernier = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
    passages = rag.rechercher(db, dernier, limite=3) if dernier else []
    system = SYSTEM_ORIENTATION.format(PRENOM=prenom)
    if passages:
        system += "\n\nRepères issus de notre base de connaissance (à utiliser sans les recopier) :\n"
        system += rag.formater_contexte(passages)

    try:
        meter = Meter(db=db, endpoint="orientation/chat",
                      user_id=user.id if user else None, piste_id=body.piste_id)
        text = llm.chat(msgs, system=system,
                        max_tokens=body.max_tokens or 700, temperature=0.75, meter=meter)
    except LLMUnavailable:
        return _mode_guide(msgs)

    return {"content": text, "mode": "IA", "pret": "[[PRET]]" in text,
            "sources": [{"titre": p.titre or p.document, "organisme": p.organisme,
                         "url": p.url} for p in passages[:3]]}


@router.post("/formations")
def formations(body: FormationsIn, db: Session = Depends(get_db),
               user: User | None = Depends(get_current_user_optional)):
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    profil = body.profil or _extraire_profil(db, msgs, user)

    charger_formations(db)                       # ingestion open data / repli seed
    resultats = top_formations(db, profil or {}, k=10)
    if not resultats:
        raise HTTPException(503, "Référentiel de formations vide — lancez l'ingestion")

    # Couverture : si rien ne relève du domaine demandé, on le dit au lieu de
    # présenter dix formations d'un autre champ comme si elles convenaient.
    # C'est le défaut qu'un étudiant en architecture rencontrait : il
    # recevait de l'informatique, sans un mot.
    dans_le_domaine = [r for r in resultats
                       if r.get("correspondance") in ("domaine", "proche")]
    couverture = {
        "domaine_demande": (profil or {}).get("domaine") or "",
        "couvert": bool(dans_le_domaine) or not (profil or {}).get("domaine"),
        "pistes_du_domaine": len(dans_le_domaine),
        "domaines_disponibles": domaines_couverts(db),
    }
    if not couverture["couvert"]:
        couverture["message"] = (
            f"Nous n'avons pas encore de formation en "
            f"« {couverture['domaine_demande']} » dans notre base. Les pistes "
            f"ci-dessous ne relèvent pas de ce domaine : elles sont "
            f"proposées à titre indicatif, sur votre niveau et votre budget. "
            f"Si vous avez déjà une école en tête, vous pouvez faire vérifier "
            f"son titre RNCP."
        )

    if body.piste_id and user:
        p = db.get(Piste, body.piste_id)
        if p and p.user_id == user.id:
            p.profil = profil or {}
            p.formations = resultats
            db.commit()
    return {"formations": resultats, "total": len(resultats), "profil": profil,
            "couverture": couverture,
            "source": "base vérifiée (scoring déterministe)"}


@router.post("/rapport")
def rapport(body: FormationsIn, db: Session = Depends(get_db),
            user: User | None = Depends(get_current_user_optional)):
    """Rapport d'orientation STRUCTURÉ (feature 1) : synthèse du projet + 10 pistes
    vérifiées + explication de la méthode (transparence, feature 2)."""
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    profil = body.profil or _extraire_profil(db, msgs, user)

    charger_formations(db)
    resultats = top_formations(db, profil or {}, k=10)
    if not resultats:
        raise HTTPException(503, "Référentiel de formations vide — lancez l'ingestion")

    synthese, mode = _synthese(db, profil or {}, user)

    if body.piste_id and user:
        p = db.get(Piste, body.piste_id)
        if p and p.user_id == user.id:
            pr = dict(profil or {})
            pr["synthese"] = synthese
            p.profil = pr
            p.formations = resultats
            db.commit()

    return {"profil": profil, "synthese": synthese, "formations": resultats,
            "total": len(resultats), "transparence": TRANSPARENCE,
            "source": "base vérifiée (scoring déterministe)", "mode": mode}


def _synthese(db: Session, profil: dict, user: User | None) -> tuple[dict, str]:
    """Synthèse rédigée par le LLM (ancrée sur le profil) ou repli déterministe."""
    llm = get_llm()
    if llm.available and profil:
        try:
            meter = Meter(db=db, endpoint="orientation/rapport",
                          user_id=user.id if user else None)
            raw = llm.chat(
                [{"role": "user", "content": RAPPORT_TEMPLATE.format(
                    profil=json.dumps(profil, ensure_ascii=False))}],
                system=SYSTEM_RAPPORT, max_tokens=500, temperature=0.4,
                json_mode=True, meter=meter)
            data = json.loads(_clean_json(raw))
            return {
                "synthese": data.get("synthese", ""),
                "forces": data.get("forces", [])[:4],
                "points_attention": data.get("points_attention", [])[:3],
                "prochaine_etape": data.get("prochaine_etape", ""),
            }, "IA"
        except Exception as e:
            logger.warning(f"Synthèse LLM échouée ({e}) — repli déterministe")
    return _synthese_guide(profil), "guidé"


def _synthese_guide(profil: dict) -> dict:
    dom = profil.get("domaine") or "votre domaine"
    niv = profil.get("niveau_vise") or profil.get("niveau") or "le niveau visé"
    pro = profil.get("projet_pro") or profil.get("resume_pro") or ""
    synth = f"Projet en {dom} au niveau {niv} pour des études en France."
    if pro:
        synth += f" Objectif professionnel : {pro}."
    forces, attention = [], []
    if profil.get("domaine"):
        forces.append(f"Domaine clair ({dom}).")
    if profil.get("projet_pro"):
        forces.append("Projet professionnel identifié.")
    if profil.get("villes_cibles"):
        forces.append("Préférence géographique définie.")
    if not profil.get("budget_annuel"):
        attention.append("Précisez votre budget annuel pour affiner les pistes.")
    if not profil.get("projet_pro"):
        attention.append("Clarifier votre objectif professionnel renforcera votre candidature.")
    attention.append("Vérifiez les dates limites Campus France de votre pays.")
    return {"synthese": synth, "forces": forces or ["Projet en cours de définition."],
            "points_attention": attention[:3],
            "prochaine_etape": "Parcourez les 10 pistes, puis passez au parcours de mobilité."}


# ── Extraction du profil (fin d'entretien) ─────────────────────────

def _extraire_profil(db: Session, msgs: list[dict], user: User | None) -> dict:
    llm = get_llm()
    if llm.available and any(m["role"] == "user" for m in msgs):
        history = "\n".join(("Étudiant" if m["role"] == "user" else "Conseiller") + ": " + m["content"]
                            for m in msgs)
        try:
            meter = Meter(db=db, endpoint="orientation/extract",
                          user_id=user.id if user else None)
            raw = llm.chat([{"role": "user", "content": EXTRACT_TEMPLATE.format(history=history)}],
                           system=SYSTEM_EXTRACT, max_tokens=500, temperature=0.1,
                           json_mode=True, leger=True, meter=meter)
            return json.loads(_clean_json(raw))
        except Exception as e:
            logger.warning(f"Extraction profil échouée ({e}) — repli questionnaire")
    return _profil_depuis_guide(msgs)


def _clean_json(raw: str) -> str:
    """Extrait l'objet JSON, qu'il soit brut ou entouré de balises ```json … ```."""
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()
    i, j = s.find("{"), s.rfind("}")
    return s[i:j + 1] if i >= 0 and j > i else s


# ── Mode guidé (sans IA) ───────────────────────────────────────────

def _mode_guide(msgs: list[dict]) -> dict:
    n_rep = sum(1 for m in msgs if m["role"] == "user")
    if n_rep >= len(GUIDE_ETAPES):
        return {"content": "Merci ! J'ai l'essentiel pour te proposer des formations. "
                           "Génère ton rapport quand tu veux.",
                "mode": "guidé", "pret": True}
    etape = GUIDE_ETAPES[n_rep]
    choices = {"question": etape["question"], "options": etape["options"], "allowOther": True}
    return {"content": f"[CHOICES]{json.dumps(choices, ensure_ascii=False)}[/CHOICES]",
            "mode": "guidé", "pret": False}


def _profil_depuis_guide(msgs: list[dict]) -> dict:
    reps = [m["content"] for m in msgs if m["role"] == "user"]
    profil = {}
    for i, etape in enumerate(GUIDE_ETAPES):
        if i < len(reps):
            profil[etape["cle"]] = [reps[i]] if etape["cle"] == "villes_cibles" else reps[i]
    return profil
