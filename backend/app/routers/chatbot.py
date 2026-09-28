"""
routers/chatbot.py — Chatbot popup de la partie payante (instruction 5).

Répond aux questions de procédure de l'étudiant, ANCRÉ sur le contenu vérifié de
l'étape en cours (il ne réinvente pas la procédure). Réservé aux pistes payées.
Mode guidé (sans IA) : renvoie le conseil et les documents officiels de l'étape.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.models import User, Piste
from app.schemas import ChatbotIn
from app.services.llm import get_llm, Meter, LLMUnavailable
from app.services.roadmap_engine import etape_par_id
from app.services import rag

router = APIRouter(prefix="/api/chatbot", tags=["chatbot"])

SYSTEME = ("Tu es l'assistant procédure de One Moov, pour un étudiant qui prépare sa "
           "mobilité vers la France. Réponds en français, de façon concrète et rassurante, "
           "en t'appuyant UNIQUEMENT sur le contexte d'étape et les passages officiels "
           "fournis. Si l'info n'y est pas, dis-le et renvoie vers la source officielle. "
           "N'invente jamais un montant, une date ou une règle. Cite les numéros [1] [2] "
           "des passages que tu utilises, l'interface transformera ces numéros en liens.")


@router.post("")
def chatbot(body: ChatbotIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(Piste, body.piste_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "Piste introuvable")
    if not p.paid:
        raise HTTPException(402, "Le chatbot fait partie de la formule payante.")

    niveau = (p.roadmap or {}).get("niveau") or ""
    etape = etape_par_id(body.etape, niveau) if body.etape else None
    contexte = ""
    if etape:
        echeance = ""
        for e in _etapes_roadmap(p):
            if e.get("id") == body.etape and e.get("echeance_str"):
                echeance = f"\nÉchéance conseillée : {e['echeance_str']} ({e.get('jours_restants')} j)"
                break
        contexte = (f"Étape : {etape['label']}\nConseil vérifié : {etape['conseil']}\n"
                    f"Documents : {', '.join(etape['docs']) or 'aucun'}{echeance}")

    # RAG : cherche les passages officiels pertinents à partir du dernier
    # message étudiant. La phase du chatbot est déduite de l'étape en cours.
    dernier = next((m.content for m in reversed(body.messages) if m.role == "user"), "")
    phase = _phase_de_etape(etape)
    passages = rag.rechercher(db, dernier, phase=phase, pays=p.pays, limite=4) if dernier else []
    bloc_passages = rag.formater_contexte(passages) if passages else ""

    llm = get_llm()
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]

    if not llm.available:
        return {"content": _guide(etape, passages), "mode": "guidé",
                "sources": [{"titre": p.titre or p.document, "organisme": p.organisme,
                             "url": p.url} for p in passages[:3]]}
    try:
        system = SYSTEME
        if contexte:
            system += f"\n\nContexte de l'étape :\n{contexte}"
        if bloc_passages:
            system += f"\n\nPassages officiels pertinents (cite leur numéro) :\n{bloc_passages}"
        meter = Meter(db=db, endpoint="chatbot", user_id=user.id, piste_id=p.id)
        text_out = llm.chat(msgs, system=system, max_tokens=500, temperature=0.4,
                            leger=True, meter=meter)
        # Repère les [1] [2] cités par le LLM pour renvoyer les vraies sources.
        import re as _re
        numeros = [int(n) for n in _re.findall(r"\[(\d+)\]", text_out or "")]
        return {"content": text_out, "mode": "IA",
                "sources": rag.sources_citees(passages, numeros)}
    except LLMUnavailable:
        return {"content": _guide(etape, passages), "mode": "guidé",
                "sources": [{"titre": p.titre or p.document, "organisme": p.organisme,
                             "url": p.url} for p in passages[:3]]}


def _phase_de_etape(etape: dict | None) -> str | None:
    """Devine la phase RAG à partir de l'étape courante de la feuille de route."""
    if not etape:
        return None
    lbl = (etape.get("phase") or etape.get("label") or "").lower()
    for phase in ("candidature", "entretien", "visa", "logement", "arrivee", "arrivée", "acceptation"):
        if phase in lbl:
            return phase.replace("é", "e")
    return None


def _etapes_roadmap(p: Piste) -> list[dict]:
    out = []
    for ph in (p.roadmap or {}).get("phases", []):
        out.extend(ph.get("etapes", []))
    return out


def _guide(etape, passages=None) -> str:
    """Réponse hors LLM : conseil officiel + passages RAG en secours."""
    base = ""
    if etape:
        base = (f"{etape['conseil']}\n\nDocuments nécessaires : "
                f"{', '.join(etape['docs']) or 'aucun'}.")
    if passages:
        extraits = []
        for i, p in enumerate(passages[:2], start=1):
            contenu = (p.contenu or "").strip()
            if len(contenu) > 500:
                contenu = contenu[:500].rsplit(" ", 1)[0] + "…"
            extraits.append(f"[{i}] {p.titre or p.document} ({p.organisme})\n{contenu}")
        if extraits:
            base = (base + "\n\n" if base else "") + "\n\n".join(extraits)
    return base or "Sélectionne une étape et je te donne les documents et le conseil officiel."
