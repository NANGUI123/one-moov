"""
services/orientation_engine.py — Sélection déterministe des 10 formations.

Cœur de la fiabilité : les formations viennent de la BASE (table `formations`),
sont filtrées et classées par des règles explicables. Le LLM ne les invente pas
et ne les reclasse pas ; il ne fait que présenter le résultat.
"""
import unicodedata
from sqlalchemy.orm import Session
from app.models import Formation

NIVEAUX_ORDRE = {"bts": 1, "but": 1, "licence": 1, "master": 2, "doctorat": 3}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _famille_niveau(s: str) -> str:
    """Ramène un niveau libre à une famille comparable (licence / master / bts / but / doctorat)."""
    s = _norm(s)
    if "master" in s or "m1" in s or "m2" in s or "mastere" in s:
        return "master"
    if "doctor" in s or "phd" in s or "these" in s:
        return "doctorat"
    if "bts" in s:
        return "bts"
    if "but" in s or "iut" in s or "dut" in s:
        return "but"
    if any(k in s for k in ("licence", "bachelor", "l1", "l2", "l3", "bac+3", "dap")):
        return "licence"
    return s


def top_formations(db: Session, profil: dict, k: int = 10) -> list[dict]:
    domaine = _norm(profil.get("domaine", ""))
    niveau = _norm(profil.get("niveau_vise") or profil.get("niveau", ""))
    budget = _to_int(profil.get("budget_annuel") or profil.get("budget_mensuel"))
    villes = [_norm(v) for v in (profil.get("villes_cibles") or [])]
    voie = _norm(profil.get("voie", ""))

    # Alias fréquents que l'extracteur LLM ou l'étudiant peut renvoyer et
    # qu'il faut rapprocher de nos libellés de base. On garde une intention :
    # ne pas exclure un domaine légitime parce qu'il a été formulé autrement.
    ALIAS = {
        "ia": "informatique", "intelligence artificielle": "informatique", "tech": "informatique",
        "developpement": "informatique", "cyber": "informatique", "data": "informatique",
        "business": "commerce gestion", "gestion": "commerce gestion", "finance": "commerce gestion",
        "marketing": "commerce gestion", "management": "commerce gestion",
        "juridique": "droit sciences po", "science politique": "droit sciences po",
        "medecine": "sante medecine", "sante": "sante medecine", "biologie": "sciences ingenierie",
        "psychologie": "lettres humaines", "sciences humaines": "lettres humaines",
        "langues": "lettres humaines", "lettres": "lettres humaines",
        "cinema": "arts design", "graphisme": "arts design", "musique": "arts design",
        "ingenieur": "sciences ingenierie", "mecanique": "sciences ingenierie",
        "physique": "sciences ingenierie", "mathematiques": "sciences ingenierie",
        "environnement": "environnement ecologie", "ecologie": "environnement ecologie",
        "energie": "environnement ecologie", "developpement durable": "environnement ecologie",
        "communication": "communication medias", "journalisme": "communication medias",
        "medias": "communication medias", "publicite": "communication medias",
        "social": "social education", "education": "social education", "enseignement": "social education",
        "assistant social": "social education", "sociologie": "social education",
        "tourisme": "tourisme hotellerie", "hotellerie": "tourisme hotellerie",
        "restauration": "tourisme hotellerie",
        "agronomie": "agriculture agronomie", "agriculture": "agriculture agronomie",
    }
    for k_al, v_al in ALIAS.items():
        if k_al in domaine:
            domaine = v_al
            break

    rows = db.query(Formation).all()
    scored = []
    for f in rows:
        score, raisons = 0, []
        fd = _norm(f.domaine)
        if domaine and (domaine in fd or fd in domaine):
            score += 40; raisons.append("domaine correspondant")
        elif domaine and _mots_communs(domaine, fd):
            score += 20; raisons.append("domaine proche")

        if niveau:
            fn, pn = _famille_niveau(f.niveau), _famille_niveau(niveau)
            if fn == pn:
                score += 25; raisons.append("niveau visé")
            elif _niveau_proche(pn, fn):
                score += 12

        if budget:
            if f.cout_annuel and f.cout_annuel <= budget:
                score += 20; raisons.append(f"coût {f.cout_annuel} € sous le budget")
            elif f.cout_annuel and f.cout_annuel <= budget * 1.3:
                score += 8
            elif f.cout_annuel > budget:
                score -= 10

        if villes and _norm(f.ville) in villes:
            score += 12; raisons.append("ville souhaitée")

        if voie and _norm(f.voie) == voie:
            score += 6

        scored.append((score, f, raisons))

    scored.sort(key=lambda x: -x[0])
    top = [t for t in scored if t[0] > 0][:k] or scored[:k]
    return [{
        "id": f.id, "intitule": f.intitule, "etablissement": f.etablissement,
        "ville": f.ville, "domaine": f.domaine, "niveau": f.niveau, "voie": f.voie,
        "cout_annuel": f.cout_annuel, "url": f.url, "code_rncp": f.code_rncp,
        "source": f.source, "score": score,
        "explication": ", ".join(raisons) or "formation du domaine",
    } for score, f, raisons in top]


def _to_int(v) -> int:
    try:
        import re
        m = re.search(r"\d+", str(v).replace(" ", ""))
        return int(m.group()) if m else 0
    except Exception:
        return 0


_STOP_DOMAINE = {"sciences", "science", "appliquees", "appliquee", "generale",
                 "etudes", "france", "professionnel", "pratique"}


def _mots_communs(a: str, b: str) -> bool:
    sa = {w for w in a.split() if len(w) > 3 and w not in _STOP_DOMAINE}
    sb = {w for w in b.split() if len(w) > 3 and w not in _STOP_DOMAINE}
    return bool(sa & sb)


def _niveau_proche(a: str, b: str) -> bool:
    return abs(NIVEAUX_ORDRE.get(a, 1) - NIVEAUX_ORDRE.get(b, 1)) <= 1
