"""Agent 2 : le chatbot d'accompagnement.

Il répond aux questions de l'étudiant sur ses démarches, en s'appuyant sur
le RAG pour le procédural et sur les faits vérifiés pour les chiffres.

Chaque réponse porte ses sources. L'étudiant voit d'où vient l'information et
peut remonter au document officiel. C'est la différence entre un assistant
qui affirme et un assistant dont on peut vérifier les dires.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.schemas import RequeteCoach, ReponseCoach
from app.services import faits as svc_faits
from app.services import rag as svc_rag
from app.services.llm import chat_json, ErreurLLM, ModeMock

logger = logging.getLogger(__name__)

SYSTEME_CHATBOT = """Tu es le chatbot d'accompagnement de One Moov. Tu accompagnes un étudiant d'Afrique centrale dans ses démarches pour étudier en France : dossier Études en France, entretien Campus France, demande de visa, logement, installation.

On te fournit des extraits de procédures officielles numérotés, et des valeurs officielles vérifiées.

Règles strictes :
- Tu n'inventes AUCUN montant, AUCUNE date limite, AUCUN quota. Tu peux citer les valeurs officielles fournies, telles quelles. Pour tout le reste, tu expliques la démarche et tu renvoies vers la source.
- Tu appuies ta réponse sur les extraits fournis et tu indiques leurs numéros dans le champ sources.
- Si les extraits ne répondent pas à la question, tu le dis franchement et tu orientes vers l'organisme compétent.
- Tu tutoies. Tu es direct et concret. Tu donnes une action faisable cette semaine.

Réponds UNIQUEMENT en JSON :
{
  "message": "ta réponse à l'étudiant",
  "prochaine_action": "une action concrète et courte",
  "sources": [1, 2],
  "suggestions": ["question de suivi courte"]
}"""


# Détection de la phase concernée, pour cibler la recherche.
#
# Ces listes servent de repli. Quand les embeddings sont actifs, la recherche
# dense rapproche déjà « garant » de « logement » sans qu'on ait à l'écrire.
# Sans eux, la recherche est purement lexicale et ce ciblage devient
# indispensable : sans lui, un mot courant comme « France » suffit à faire
# remonter n'importe quel passage.
MOTS_PHASE = {
    "candidature": [
        "dossier", "candidature", "candidater", "eef", "études en france",
        "inscription", "inscrire", "pièce", "pieces", "postuler", "vœu", "voeu",
        "relevé", "releve", "diplôme", "diplome", "traduction", "assermenté",
        "frais de dossier", "espace personnel", "lettre de motivation",
    ],
    "entretien": [
        "entretien", "jury", "oral", "convocation", "motivation",
        "me préparer", "préparer l'entretien", "questions posées",
    ],
    "visa": [
        "visa", "consulat", "consulaire", "ambassade", "vls", "vlsts",
        "ressources", "justificatif", "compte bloqué", "somme bloquée",
        "garant financier", "prise en charge", "refus de visa", "recours",
        "france-visas", "rendez-vous",
    ],
    "logement": [
        "logement", "loger", "louer", "location", "loyer", "bail", "locataire",
        "garant", "garantie", "visale", "caution", "dépôt de garantie",
        "chambre", "studio", "appartement", "colocation", "résidence", "crous",
        "apl", "caf", "aide au logement", "hébergement",
    ],
    "arrivee": [
        "arrivée", "arriver", "installation", "installer", "banque",
        "compte bancaire", "rib", "sécurité sociale", "sécu", "mutuelle",
        "titre de séjour", "valider mon visa", "validation du visa",
        "travailler", "job", "emploi étudiant", "heures de travail",
    ],
    "acceptation": [
        "réponse", "acceptation", "accepté", "admis", "admission",
        "refus", "refusé", "liste d'attente", "résultat",
    ],
}


def _deviner_phase(message: str, etape_courante: str | None) -> str | None:
    """Repère la phase concernée par la question.

    On compte les correspondances plutôt que de s'arrêter à la première :
    « je n'ai pas de garant pour louer » touche deux mots de logement et
    aucun ailleurs, donc la phase est certaine. À égalité, on ne tranche pas
    et on laisse la recherche porter sur toute la base.
    """
    texte = (message or "").lower()

    scores = {
        phase: sum(1 for mot in mots if mot in texte)
        for phase, mots in MOTS_PHASE.items()
    }
    meilleur = max(scores.values())

    if meilleur > 0:
        gagnantes = [p for p, s in scores.items() if s == meilleur]
        if len(gagnantes) == 1:
            return gagnantes[0]

    # Aucun mot reconnu : on se rabat sur l'étape en cours de la feuille de route.
    if etape_courante:
        courante = etape_courante.lower()
        for phase in MOTS_PHASE:
            if phase in courante:
                return phase

    return None


def repondre(db: Session, requete: RequeteCoach) -> ReponseCoach:
    """Répond à une question de l'étudiant."""
    message = requete.message.strip()

    if not message:
        return _accueil(db, requete)

    phase = _deviner_phase(message, requete.etape_courante)

    # Recherche dans la connaissance procédurale.
    passages = svc_rag.rechercher(
        db, message, phase=phase, pays=requete.profil.pays_origine, limite=5
    )

    # Faits vérifiés applicables.
    liste_faits = svc_faits.pour_pays(db, requete.profil.pays_origine)

    contexte = [
        "Profil de l'étudiant :",
        requete.profil.model_dump_json(indent=2, exclude_none=True),
        "",
        f"Étape en cours : {requete.etape_courante or 'non précisée'}",
        "",
        "Extraits de procédures officielles :",
        svc_rag.formater_contexte(passages),
        "",
        "Valeurs officielles vérifiées :",
        svc_faits.formater_pour_prompt(liste_faits),
        "",
        "Échange précédent :",
        "\n".join(
            f"{'Étudiant' if m.role == 'etudiant' else 'Coach'} : {m.texte}"
            for m in requete.historique[-6:]
        ) or "(début de l'échange)",
        "",
        f"Question de l'étudiant : {message}",
    ]

    try:
        brut = chat_json(SYSTEME_CHATBOT, "\n".join(contexte), temperature=0.4, max_tokens=1100,
                          fonction="chatbot")
    except (ModeMock, ErreurLLM) as e:
        if isinstance(e, ErreurLLM):
            logger.warning("Coach en mode dégradé : %s", e)
        return _reponse_sans_modele(passages, liste_faits, phase)

    sources = svc_rag.sources_citees(passages, brut.get("sources") or [])
    if not sources and passages:
        sources = svc_rag.sources_citees(passages, [1])

    # Seuls les faits de la phase concernée sont renvoyés, pour ne pas
    # noyer l'étudiant sous des valeurs qui ne le concernent pas encore.
    faits_pertinents = _faits_de_phase(liste_faits, phase)

    return ReponseCoach(
        message=str(brut.get("message") or ""),
        prochaine_action=str(brut.get("prochaine_action") or "") or None,
        faits=[f.to_dict() for f in faits_pertinents],
        sources=sources,
        suggestions=[str(s) for s in (brut.get("suggestions") or [])][:3],
    )


def _accueil(db: Session, requete: RequeteCoach) -> ReponseCoach:
    """Premier message, sans appel au modèle : rapide et prévisible."""
    etape = requete.etape_courante or "ta première étape"
    return ReponseCoach(
        message=(
            "Bonjour, je suis ton assistant One Moov. Je t'accompagne sur chaque démarche, "
            f"de ton dossier jusqu'à ton arrivée. Tu en es à {etape}. "
            "Dis-moi ce qui te bloque ou ce que tu veux comprendre."
        ),
        prochaine_action="Reprends ta feuille de route et repère l'étape en cours.",
        faits=[],
        sources=[],
        suggestions=[
            "Quelles pièces pour mon dossier ?",
            "Comment se passe l'entretien ?",
            "Que demande le consulat pour le visa ?",
        ],
    )


def _reponse_sans_modele(passages, liste_faits, phase) -> ReponseCoach:
    """Réponse de secours structurée à partir de plusieurs sources RAG.

    Même sans LLM, le Cat Bot doit donner une réponse exploitable : contexte,
    étapes concrètes, puis source officielle. On évite donc l'ancien comportement
    qui affichait uniquement le premier passage tronqué.
    """
    if not passages:
        return ReponseCoach(
            message=(
                "Je n'ai pas d'élément fiable sur ce point dans ma base de connaissance. "
                "Vérifie la procédure sur le site officiel de l'organisme concerné avant d'agir."
            ),
            faits=[],
            sources=[],
            suggestions=[],
        )

    morceaux = []
    numeros = []
    for index, extrait in enumerate(passages[:3], start=1):
        corps = (extrait.contenu or "").strip()
        if len(corps) > 650:
            corps = corps[:650].rsplit(" ", 1)[0] + "…"
        morceaux.append(f"{extrait.titre or extrait.document}\n{corps}")
        numeros.append(index)

    prochaines_actions = {
        "candidature": "Vérifie les pièces demandées dans ton espace Études en France et complète en priorité celles qui manquent.",
        "entretien": "Prépare une réponse personnelle sur ton parcours, ta formation visée, ton financement et ton projet professionnel.",
        "acceptation": "Après réception des réponses, compare les établissements puis valide ton choix définitif avant la date limite affichée dans ton dossier.",
        "visa": "Ouvre France-Visas, renseigne ta situation et utilise la liste de pièces générée pour préparer ton dossier et ton rendez-vous.",
        "logement": "Commence les recherches auprès de sources fiables et prépare ton dossier locatif avant de verser une somme.",
        "arrivee": "À l'arrivée, traite d'abord la validation du visa puis les démarches d'installation indiquées dans ta feuille de route.",
    }
    action = prochaines_actions.get(phase or "", "Vérifie les informations indiquées puis ouvre la source officielle avant d'agir.")

    faits = _faits_de_phase(liste_faits, phase)
    if faits:
        bloc_faits = "\n\nValeurs vérifiées associées :\n" + "\n".join(
            f"• {f.libelle or f.cle} : {f.valeur}" for f in faits
        )
    else:
        bloc_faits = ""

    return ReponseCoach(
        message="Voici les éléments officiels les plus utiles pour cette étape.\n\n" +
                "\n\n".join(morceaux) + bloc_faits,
        prochaine_action=action,
        faits=[f.to_dict() for f in faits],
        sources=svc_rag.sources_citees(passages, numeros),
        suggestions=[
            "Quelles pièces dois-je préparer ?" if phase == "visa" else "Quelle est la prochaine étape ?",
            "Peux-tu me donner les démarches à faire ?",
        ],
    )


def _faits_de_phase(liste_faits, phase):
    correspondance = {
        "candidature": {"frais_dossier_campus_france"},
        "visa": {"seuil_ressources_visa", "montant_bloque_sans_logement",
                 "montant_bloque_avec_logement", "delai_validation_vlsts"},
        "logement": {"montant_bloque_avec_logement"},
        "arrivee": {"quota_heures_travail", "delai_validation_vlsts"},
    }
    cles = correspondance.get(phase or "", set())
    return [f for f in liste_faits if f.cle in cles]
