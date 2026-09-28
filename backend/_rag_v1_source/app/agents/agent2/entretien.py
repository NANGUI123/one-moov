"""Agent 2 : la simulation d'entretien.

Deux rôles séparés, et c'est un choix de conception, pas un détail :

    le jury      pose la question. Température élevée, pour varier les
                 formulations d'une session à l'autre.
    le correcteur note la réponse. Température nulle, un seul critère à la
                 fois, barème explicite.

Si un même appel jouait et notait, il aurait tendance à valoriser les
réponses à ses propres questions. En séparant, la note devient reproductible :
la même réponse obtient la même note, ce que vérifient les tests.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from app.models.schemas import (
    RequeteQuestion, ReponseQuestion, RequeteEvaluation, ReponseEvaluation,
    TypeEntretien,
)
from app.services import rag as svc_rag
from app.services.llm import chat_json, ErreurLLM, ModeMock

logger = logging.getLogger(__name__)

# Grille d'évaluation. Les critères reprennent ceux de l'entretien
# pédagogique Campus France. Les pondérations sont à caler avec l'espace
# Campus France du pays avant toute utilisation réelle.
CRITERES_CAMPUS = {
    "coherence_projet": ("Cohérence du parcours et de la formation visée", 25),
    "motivation_formation": ("Motivation pour la formation et l'établissement", 20),
    "projet_professionnel": ("Projet professionnel et retour au pays", 20),
    "connaissance_france": ("Connaissance de la France et de l'établissement", 15),
    "capacite_financement": ("Capacité de financement du séjour", 10),
    "expression": ("Clarté de l'expression", 10),
}

CRITERES_AMBASSADE = {
    "motif_sejour": ("Motif et cohérence du séjour", 20),
    "connaissance_formation": ("Connaissance de la formation et de l'établissement", 20),
    "financement": ("Financement et ressources pour le séjour", 20),
    "logement_sejour": ("Logement et organisation du séjour", 15),
    "projet_apres_etudes": ("Projet après les études et situation personnelle", 15),
    "fiabilite_dossier": ("Cohérence et précision des informations du dossier", 10),
}

QUESTIONS_SECOURS = {
    "campus_france": {
        "coherence_projet": "En quoi cette formation prolonge-t-elle ton parcours actuel ?",
        "motivation_formation": "Pourquoi cet établissement et cette formation en particulier ?",
        "projet_professionnel": "Quel métier vises-tu après ton diplôme, et quel lien avec ton pays d'origine ?",
        "connaissance_france": "Que sais-tu de la ville et de l'établissement où tu souhaites étudier ?",
        "capacite_financement": "Comment financeras-tu tes études, ton logement et ta vie quotidienne en France ?",
        "expression": "Présente-toi, ton parcours et ton projet d'études en quelques phrases.",
    },
    "ambassade": {
        "motif_sejour": "Pourquoi veux-tu venir en France précisément pour ce projet d'études ?",
        "connaissance_formation": "Que peux-tu expliquer sur ta formation, ton établissement et le diplôme que tu vas préparer ?",
        "financement": "Qui finance concrètement ton séjour et quelles ressources peux-tu justifier ?",
        "logement_sejour": "Où vas-tu vivre en France à ton arrivée et comment as-tu préparé ton séjour ?",
        "projet_apres_etudes": "Que comptes-tu faire après tes études et quel est ton projet à moyen terme ?",
        "fiabilite_dossier": "Peux-tu expliquer les principales informations de ton dossier et pourquoi elles sont cohérentes entre elles ?",
    },
}


SYSTEME_JURY = """Tu joues un membre du jury lors d'un entretien. Tu poses UNE seule question, dans un français clair, sur un ton professionnel, bienveillant mais exigeant.

Le contexte de l'entretien et le critère à aborder te sont donnés. Ta question doit porter précisément sur ce critère, et tenir compte du profil de l'étudiant pour être concrète.

Réponds UNIQUEMENT en JSON : {"question": "ta question"}"""

SYSTEME_CORRECTEUR = """Tu évalues la réponse d'un étudiant à une question d'entretien, sur un seul critère donné.

Barème de 0 à 5 :
0 aucune réponse.
1 hors sujet.
2 trop vague, aucun élément concret.
3 correct mais général, sans exemple personnel.
4 bonne réponse, argumentée, avec au moins un élément concret.
5 précise, argumentée et personnelle, avec des éléments vérifiables.

Tu évalues UNIQUEMENT le critère indiqué. Tu ne juges ni l'orthographe, ni la personne, ni son niveau de langue au-delà de ce que le critère demande.

Réponds UNIQUEMENT en JSON :
{"note": 3, "commentaire": "une phrase qui dit ce qui manque ou ce qui est réussi", "conseil": "une phrase d'amélioration concrète"}"""


def poser_question(db: Session, requete: RequeteQuestion) -> ReponseQuestion:
    """Le jury pose la question suivante."""
    type_cle = "campus_france" if requete.type_entretien == TypeEntretien.campus_france else "ambassade"
    criteres = CRITERES_CAMPUS if type_cle == "campus_france" else CRITERES_AMBASSADE
    ordre_criteres = list(criteres.keys())
    restants = [c for c in ordre_criteres if c not in requete.criteres_poses]
    critere = restants[0] if restants else ordre_criteres[-1]
    libelle = criteres[critere][0]

    contexte_entretien = (
        "entretien pédagogique Campus France"
        if requete.type_entretien == TypeEntretien.campus_france
        else "entretien consulaire à l'ambassade, pour la demande de visa"
    )

    # Le RAG apporte au jury ce que l'entretien évalue réellement, pour que
    # ses questions restent ancrées dans la procédure.
    passages = svc_rag.rechercher(
        db, f"{contexte_entretien} attentes du jury", phase="entretien",
        pays=requete.profil.pays_origine, limite=2,
    )

    contexte = [
        f"Type d'entretien : {contexte_entretien}",
        "",
        "Profil de l'étudiant :",
        requete.profil.model_dump_json(indent=2, exclude_none=True),
        "",
        "Ce que cet entretien évalue, d'après la procédure officielle :",
        svc_rag.formater_contexte(passages),
        "",
        f"Critère à aborder maintenant : {libelle}",
        f"Critères déjà abordés : {', '.join(requete.criteres_poses) or 'aucun'}",
    ]

    try:
        brut = chat_json(SYSTEME_JURY, "\n".join(contexte), temperature=0.8, max_tokens=250,
                          fonction="chatbot")
        question = str(brut.get("question") or "").strip()
    except (ModeMock, ErreurLLM):
        question = ""

    return ReponseQuestion(
        question=question or QUESTIONS_SECOURS[type_cle][critere],
        critere=critere,
        critere_libelle=libelle,
        restants=max(0, len(restants) - 1),
    )


def evaluer(requete: RequeteEvaluation) -> ReponseEvaluation:
    """Le correcteur note la réponse, sur le seul critère demandé."""
    criteres = {**CRITERES_CAMPUS, **CRITERES_AMBASSADE}
    critere = requete.critere if requete.critere in criteres else "coherence_projet"
    libelle = criteres[critere][0]
    texte = requete.reponse.strip()

    if not texte:
        return ReponseEvaluation(
            note=0, critere=critere, critere_libelle=libelle,
            commentaire="Aucune réponse fournie.",
            conseil="Prends le temps de formuler une réponse, même courte.",
        )

    contexte = [
        f"Critère évalué : {libelle}",
        f"Question posée : {requete.question}",
        f"Réponse de l'étudiant : {texte}",
    ]

    try:
        # Température nulle : la même réponse doit obtenir la même note.
        brut = chat_json(SYSTEME_CORRECTEUR, "\n".join(contexte), temperature=0.0, max_tokens=350,
                          fonction="chatbot")
        note = max(0, min(5, int(brut.get("note", 0))))
        return ReponseEvaluation(
            note=note,
            critere=critere,
            critere_libelle=libelle,
            commentaire=str(brut.get("commentaire") or ""),
            conseil=str(brut.get("conseil") or ""),
        )
    except (ModeMock, ErreurLLM) as e:
        if isinstance(e, ErreurLLM):
            logger.warning("Notation en mode dégradé : %s", e)
        return _noter_sans_modele(texte, critere, libelle)


def _noter_sans_modele(texte: str, critere: str, libelle: str) -> ReponseEvaluation:
    """Notation de secours, déterministe.

    Elle mesure ce qui est mesurable sans modèle : la longueur, la présence
    d'arguments et d'éléments concrets. Moins fine qu'une vraie évaluation,
    mais reproductible et jamais absurde.
    """
    mots = len([m for m in re.split(r"\s+", texte) if m])

    note = 2 if mots else 0
    if mots >= 25:
        note += 1
    if re.search(r"\b(parce que|car|afin de|pour|puisque)\b", texte, re.I):
        note += 1
    if mots >= 50 and re.search(r"\b(objectif|métier|projet|retour|expérience|stage|diplôme)\b", texte, re.I):
        note += 1
    note = min(note, 5)

    commentaires = {
        0: "Aucune réponse fournie.",
        1: "La réponse ne répond pas à la question posée.",
        2: "Trop vague. Le jury attend des éléments concrets tirés de ton parcours.",
        3: "Correct, mais reste général. Ajoute un exemple précis.",
        4: "Bonne réponse, argumentée. Développe encore d'un cran.",
        5: "Réponse précise, argumentée et personnelle.",
    }
    return ReponseEvaluation(
        note=note, critere=critere, critere_libelle=libelle,
        commentaire=commentaires[note],
        conseil="Appuie chaque affirmation sur un fait de ton parcours ou un objectif daté.",
    )


def grille() -> list[dict]:
    """Les deux grilles d'entretien, pour affichage et diagnostic."""
    lignes = []
    for type_cle, criteres in (("campus_france", CRITERES_CAMPUS), ("ambassade", CRITERES_AMBASSADE)):
        for cle, (libelle, poids) in criteres.items():
            lignes.append({"type": type_cle, "critere": cle, "libelle": libelle, "poids": poids})
    return lignes
