"""
services/roadmap_engine.py — Génère la feuille de route à partir du pack procédure
VÉRIFIÉ. Deux nouveautés majeures :

1. Moteur d'échéances (feature 3) : à partir d'une date d'ancrage (la rentrée visée),
   chaque étape reçoit une date cible, un décompte de jours et un niveau d'urgence
   (fait / retard / bientôt / à venir). La « prochaine action » est enrichie de son échéance.
2. Entonnoir par niveau (feature 7) : la procédure s'adapte au niveau visé
   (L1/DAP, L2-L3, Master, BTS).

Le graphe de dépendances ouvre une étape quand ses prérequis sont faits ; plusieurs
branches (AVI, logement, assurance) avancent en parallèle.
"""
from datetime import date, datetime, timedelta

from app.data.procedures.france import (
    ETAPES_FRANCE, SOURCE, DATE_VERIF, RENTREE_MOIS,
    ADAPTATIONS, NIVEAUX_IDS,
)

PHASES_ORDRE = ["Candidature", "Documents", "Visa", "Arrivée"]

_MOIS_FR = ["", "janv.", "févr.", "mars", "avr.", "mai", "juin",
            "juil.", "août", "sept.", "oct.", "nov.", "déc."]


# ── Adaptation par niveau ──────────────────────────────────────────

def etapes_pour_niveau(niveau: str | None) -> list[dict]:
    """Renvoie les étapes, en appliquant les surcharges propres au niveau visé."""
    adapt = ADAPTATIONS.get((niveau or "").strip()) or {}
    out = []
    for e in ETAPES_FRANCE:
        e2 = dict(e)
        if e["id"] in adapt:
            e2.update(adapt[e["id"]])
        out.append(e2)
    return out


# ── Dates & échéances ──────────────────────────────────────────────

def rentree_par_defaut(today: date | None = None) -> date:
    """Prochaine rentrée (1er septembre). On bascule sur l'année suivante s'il reste
    trop peu de temps pour un cycle complet (< 120 jours)."""
    today = today or date.today()
    cible = date(today.year, RENTREE_MOIS, 1)
    if (cible - today).days < 120:
        cible = date(today.year + 1, RENTREE_MOIS, 1)
    return cible


def _parse_anchor(anchor: str | None) -> date:
    if anchor:
        try:
            return datetime.strptime(anchor[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return rentree_par_defaut()


def _fr_date(d: date) -> str:
    return f"{d.day} {_MOIS_FR[d.month]} {d.year}"


def _urgence(statut: str, jours_restants: int) -> str:
    if statut == "fait":
        return "fait"
    if jours_restants < 0:
        return "retard"
    if jours_restants <= 30:
        return "bientot"
    return "avenir"


def statut_etape(etape: dict, done: set[str]) -> str:
    if etape["id"] in done:
        return "fait"
    if all(d in done for d in etape["depends_on"]):
        return "ouvert"
    return "verrouille"


# ── Construction de l'arbre ────────────────────────────────────────

def build_tree(voie: str, niveau: str | None = None, done: set[str] | None = None,
               anchor: str | None = None, formation_privee: dict | None = None) -> dict:
    done = done or set()
    rentree = _parse_anchor(anchor)
    today = date.today()
    base = etapes_pour_niveau(niveau)

    etapes = []
    for e in base:
        statut = statut_etape(e, done)
        echeance = rentree - timedelta(days=int(e.get("avant_rentree_jours", 0)))
        jours_restants = (echeance - today).days
        etapes.append({
            **e,
            "statut": statut,
            "critique": bool(e.get("critique")),
            "echeance": echeance.isoformat(),
            "echeance_str": _fr_date(echeance),
            "jours_restants": jours_restants,
            "urgence": _urgence(statut, jours_restants),
        })

    phases = []
    for ph in PHASES_ORDRE:
        items = [e for e in etapes if e["phase"] == ph]
        if items:
            phases.append({"phase": ph, "etapes": items})

    total = len(etapes)
    faits = sum(1 for e in etapes if e["statut"] == "fait")

    # Prochaine action = 1re étape ouverte (dans l'ordre chronologique de la procédure).
    prochaine = next((e for e in etapes if e["statut"] == "ouvert"), None)

    # Alerte : étapes ouvertes en retard, ou échéance critique imminente.
    en_retard = [e for e in etapes if e["urgence"] == "retard" and e["statut"] != "verrouille"]
    critiques_a_venir = sorted(
        [e for e in etapes if e["critique"] and e["statut"] != "fait" and e["jours_restants"] >= 0],
        key=lambda e: e["jours_restants"],
    )
    prochaine_critique = critiques_a_venir[0] if critiques_a_venir else None

    return {
        "voie": voie or "public",
        "niveau": (niveau or ""),
        "rentree": rentree.isoformat(),
        "rentree_str": _fr_date(rentree),
        "formation_privee": formation_privee or {},
        "phases": phases,
        "progression_pct": round(100 * faits / total) if total else 0,
        "etapes_total": total,
        "etapes_faites": faits,
        "prochaine_action": _action_dict(prochaine) if prochaine else None,
        "nb_en_retard": len(en_retard),
        "prochaine_critique": _action_dict(prochaine_critique) if prochaine_critique else None,
        "source": SOURCE,
        "date_verif": DATE_VERIF,
    }


def _action_dict(e: dict) -> dict:
    return {"id": e["id"], "label": e["label"], "conseil": e["conseil"],
            "critique": e.get("critique", False), "echeance_str": e.get("echeance_str", ""),
            "jours_restants": e.get("jours_restants"), "urgence": e.get("urgence")}


def etape_par_id(step_id: str, niveau: str | None = None) -> dict | None:
    return next((e for e in etapes_pour_niveau(niveau) if e["id"] == step_id), None)
