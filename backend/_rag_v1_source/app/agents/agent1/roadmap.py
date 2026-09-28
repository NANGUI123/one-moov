"""Agent 1, étape 3 : la feuille de route.

C'est ici que les trois sources se rejoignent, chacune dans son rôle :

    la base       fournit les établissements, les villes et les coûts
    les faits     fournissent les montants, seuils et délais vérifiés
    le RAG        fournit le procédural, avec la référence du document
    le modèle     rédige, relie, et personnalise. Il ne produit aucun chiffre.

Si le modèle est indisponible, la feuille de route est tout de même produite
à partir de la base, du RAG et des faits. Elle est moins personnalisée, mais
elle reste juste. C'est le comportement voulu : on préfère une feuille de
route sobre à une absence de feuille de route.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.schemas import (
    Profil, Roadmap, EtapeRoadmap, Secteur,
)
from app.agents.agent1 import matching
from app.services import faits as svc_faits
from app.services import rag as svc_rag
from app.services.llm import chat_json, ErreurLLM, ModeMock

logger = logging.getLogger(__name__)

# Les phases de la procédure, dans l'ordre. Cette séquence est fixe : elle
# vient de la procédure officielle, pas d'une génération.
PHASES = [
    ("candidature", "Constituer ton dossier Études en France",
     "Rassembler les pièces, compléter ton dossier et respecter le calendrier de candidature."),
    ("entretien", "Préparer et passer ton entretien",
     "Préparer la présentation de ton parcours, ton projet d'études, ton projet professionnel et tes motivations."),
    ("acceptation", "Recevoir les réponses et valider ton établissement",
     "Après les réponses des établissements, comparer les propositions puis valider ton choix définitif avant la date limite indiquée dans ton dossier."),
    ("visa", "Déposer ta demande de visa",
     "Préparer les justificatifs demandés, prendre le rendez-vous compétent et suivre la demande de visa."),
    ("depart", "Préparer ton départ",
     "Une fois la demande de visa déposée, organiser le voyage, les bagages, l'arrivée sur place et les premiers jours en France."),
    ("arrivee", "Préparer ton arrivée en France",
     "À ton arrivée, effectuer les démarches essentielles, rejoindre ton établissement et finaliser ton installation."),
]


ACTIONS_SECOURS = {
    "candidature": [
        "Compléter ton espace Études en France avec les informations de ton parcours.",
        "Vérifier les pièces et les traductions demandées avant de valider le dossier.",
        "Conserver une copie des justificatifs et des confirmations d'envoi.",
    ],
    "entretien": [
        "Préparer une présentation courte de ton parcours et de ton projet d'études.",
        "Relier la formation choisie à ton projet professionnel.",
        "Préparer une réponse concrète sur le financement, le logement et la vie en France.",
    ],
    "acceptation": [
        "Consulter les réponses reçues des établissements.",
        "Comparer les formations et les établissements qui t'ont répondu.",
        "Valider ton choix définitif avant la date limite affichée dans ton dossier.",
    ],
    "visa": [
        "Créer ou compléter ta demande sur France-Visas.",
        "Utiliser la liste de pièces générée pour ton profil et préparer le rendez-vous.",
        "Conserver la preuve du dépôt et suivre l'évolution de la demande.",
    ],
    "depart": [
        "Une fois le visa obtenu, réserver ton billet et vérifier les conditions de voyage.",
        "Préparer ton passeport, ton visa, tes justificatifs d'inscription et tes documents importants.",
        "Prévoir les premières dépenses, le trajet jusqu'au logement et les coordonnées de l'établissement.",
    ],
    "arrivee": [
        "Valider ton visa long séjour selon les démarches prévues après l'entrée en France.",
        "Effectuer les démarches d'installation : établissement, logement, sécurité sociale et compte bancaire.",
        "Conserver les confirmations de toutes les démarches réalisées.",
    ],
}


SYSTEME_ROADMAP = """Tu es l'agent d'orientation de One Moov. Tu rédiges la feuille de route d'un étudiant d'Afrique centrale qui prépare des études en France.

On te fournit des éléments déjà vérifiés : des établissements issus de notre base, des valeurs officielles sourcées, et des extraits de procédures officielles numérotés.

Règles strictes :
- Tu n'inventes AUCUN montant, AUCUNE date limite, AUCUN quota. Si une valeur t'est fournie dans les données officielles, tu peux la citer telle quelle. Sinon, tu n'en donnes pas.
- Tu ne cites aucun établissement qui ne figure pas dans la liste fournie.
- Pour chaque étape, indique les numéros des extraits que tu as utilisés dans le champ sources.
- Tu tutoies, tu es concret et bref.

Réponds UNIQUEMENT en JSON :
{
  "resume": "deux phrases qui résument le projet de l'étudiant",
  "pourquoi_etablissements": {"identifiant_etablissement": "une phrase liant cet établissement au projet"},
  "etapes": [
    {"phase": "candidature", "titre": "...", "description": "deux à trois phrases concrètes", "actions": ["action courte"], "sources": [1, 3]}
  ]
}

Le champ etapes reprend exactement les phases fournies, dans le même ordre. Les actions doivent être très concrètes et directement applicables."""


def generer(db: Session, profil: Profil, secteurs: list[Secteur]) -> Roadmap:
    """Compose la feuille de route complète."""

    # 1. Base : établissements et villes.
    etablissements = matching.chercher_etablissements(db, profil, secteurs)
    villes = matching.villes_des_etablissements(db, etablissements)
    if not villes:
        villes = matching.villes_dans_budget(db, profil.budget_mensuel)
    analyse = matching.analyser_budget(profil, villes)

    # 2. Faits vérifiés applicables au pays de départ.
    faits = svc_faits.pour_pays(db, profil.pays_origine)

    # 3. RAG : le procédural de chaque phase.
    passages_par_phase: dict[str, list] = {}
    for phase, titre, _ in PHASES:
        requete = f"{titre} {profil.pays_origine or ''} études en France"
        passages_par_phase[phase] = svc_rag.rechercher(
            db, requete, phase=phase, pays=profil.pays_origine, limite=3
        )

    # 4. Rédaction.
    redaction = _rediger(profil, etablissements, faits, passages_par_phase)

    etapes = _assembler_etapes(redaction, passages_par_phase, faits, profil)

    for e in etablissements:
        e.pourquoi = (redaction.get("pourquoi_etablissements") or {}).get(e.id)

    return Roadmap(
        resume=redaction.get("resume") or _resume_secours(profil),
        analyse_budget=analyse,
        villes=villes,
        etablissements=etablissements,
        etapes=etapes,
        faits_cles=[f.to_dict() for f in faits],
        genere_le=datetime.now(timezone.utc).isoformat(),
        version_connaissance=svc_rag.etat(db),
    )


def _rediger(profil, etablissements, faits, passages_par_phase) -> dict:
    """Appelle le modèle pour la partie rédactionnelle.

    En cas d'échec, renvoie un dictionnaire vide : l'assemblage retombe
    alors sur les descriptions de base.
    """
    liste_etabs = "\n".join(
        f"- {e.id} : {e.nom} ({e.ville}, {e.secteur}, {e.frais_scolarite_an} € par an)"
        for e in etablissements
    ) or "(aucun établissement retenu)"

    contexte_rag = []
    numero = 1
    index_global: list = []
    for phase, _, _ in PHASES:
        for p in passages_par_phase.get(phase, []):
            contexte_rag.append(f"[{numero}] ({phase}) {p.titre or p.document} : {p.contenu}")
            index_global.append(p)
            numero += 1

    contexte = [
        "Profil de l'étudiant :",
        profil.model_dump_json(indent=2, exclude_none=True),
        "",
        "Établissements retenus par notre base, les seuls que tu peux citer :",
        liste_etabs,
        "",
        "Valeurs officielles vérifiées, les seules que tu peux citer :",
        svc_faits.formater_pour_prompt(faits),
        "",
        "Extraits de procédures officielles :",
        "\n\n".join(contexte_rag) or "(aucun extrait disponible)",
        "",
        "Phases à couvrir, dans cet ordre :",
        "\n".join(f"- {phase} : {titre}" for phase, titre, _ in PHASES),
    ]

    try:
        return chat_json(SYSTEME_ROADMAP, "\n".join(contexte), temperature=0.3, max_tokens=2400,
                         fonction="roadmap")
    except ModeMock:
        return {}
    except ErreurLLM as e:
        logger.warning("Feuille de route rédigée sans le modèle : %s", e)
        return {}


def _liens_pour_phase(profil: Profil, phase: str) -> list[dict]:
    """Liens concrets affichés au bon moment du parcours, selon le pays."""
    pays = (profil.pays_origine or "").lower()
    base = {
        "candidature": [
            {"label": "Campus France", "url": "https://www.campusfrance.org/fr"},
            {"label": "Études en France / Pastel", "url": "https://pastel.diplomatie.gouv.fr/etudesenfrance/dyn/public/authentification/login.html"},
        ],
        "entretien": [
            {"label": "Campus France", "url": "https://www.campusfrance.org/fr"},
        ],
        "acceptation": [
            {"label": "Campus France", "url": "https://www.campusfrance.org/fr"},
        ],
        "visa": [
            {"label": "France-Visas", "url": "https://france-visas.gouv.fr/"},
        ],
        "depart": [
            {"label": "Réserver un vol — Google Flights", "url": "https://www.google.com/travel/flights"},
            {"label": "Air France", "url": "https://wwws.airfrance.fr/"},
        ],
        "arrivee": [
            {"label": "Service-Public.fr", "url": "https://www.service-public.fr/"},
            {"label": "Ameli — étudiant étranger", "url": "https://etudiant-etranger.ameli.fr/"},
            {"label": "CAF", "url": "https://www.caf.fr/"},
        ],
    }

    if "cameroun" in pays:
        base["candidature"] = [
            {"label": "Campus France Cameroun", "url": "https://www.cameroun.campusfrance.org/fr/etudier-en-france"},
            {"label": "Calendrier et étapes de candidature", "url": "https://www.cameroun.campusfrance.org/fr/consultez-ici-calendrier-de-candidatures"},
            {"label": "Études en France / Pastel", "url": "https://pastel.diplomatie.gouv.fr/etudesenfrance/dyn/public/authentification/login.html"},
        ]
        base["acceptation"] = [
            {"label": "Campus France Cameroun", "url": "https://www.cameroun.campusfrance.org/fr/etudier-en-france"},
        ]
        base["arrivee"].append({"label": "Campus France Cameroun — Arriver en France", "url": "https://www.cameroun.campusfrance.org/fr/arriver-en-france"})
    elif "congo" in pays:
        base["candidature"] = [
            {"label": "Campus France Congo", "url": "https://www.congobrazzaville.campusfrance.org/comment-venir-etudier-en-france"},
            {"label": "Les 8 étapes de la procédure", "url": "https://www.congobrazzaville.campusfrance.org/les-8-etapes-de-la-procedure"},
            {"label": "Études en France / Pastel", "url": "https://pastel.diplomatie.gouv.fr/etudesenfrance/dyn/public/authentification/login.html"},
        ]
        base["acceptation"] = [
            {"label": "Campus France Congo", "url": "https://www.congobrazzaville.campusfrance.org/les-8-etapes-de-la-procedure"},
        ]
        base["arrivee"].append({"label": "Campus France Congo — Préparer son séjour", "url": "https://www.congobrazzaville.campusfrance.org/comment-venir-etudier-en-france"})

    return base.get(phase, [])


def _assembler_etapes(redaction, passages_par_phase, faits, profil) -> list[EtapeRoadmap]:
    """Construit les étapes en attachant sources et faits à chacune.

    L'ordre et les phases sont imposés par le code, pas par le modèle. Ce
    dernier ne peut ni en ajouter, ni en supprimer, ni en changer l'ordre.
    """
    par_phase = {e.get("phase"): e for e in (redaction.get("etapes") or []) if isinstance(e, dict)}

    # Rattachement des faits aux phases qui les concernent.
    faits_par_phase = {
        "candidature": ["frais_dossier_campus_france"],
        "visa": ["seuil_ressources_visa", "montant_bloque_sans_logement",
                 "montant_bloque_avec_logement", "delai_validation_vlsts"],
        "arrivee": ["quota_heures_travail", "delai_validation_vlsts"],
    }
    index_faits = {f.cle: f for f in faits}

    etapes = []
    for ordre, (phase, titre_defaut, description_defaut) in enumerate(PHASES, start=1):
        redige = par_phase.get(phase, {})
        passages = passages_par_phase.get(phase, [])

        description = str(redige.get("description") or description_defaut)
        actions = [str(a) for a in (redige.get("actions") or ACTIONS_SECOURS.get(phase, []))][:5]

        if phase == "candidature":
            pays = profil.pays_origine or "ton pays de résidence"
            note_paiement = (
                f"Le paiement des frais Campus France dépend du pays de résidence ({pays}) et de la procédure suivie. "
                "Le montant, le moment du paiement et l'organisme destinataire doivent être vérifiés dans ton espace officiel avant de payer. "
                "Conserve systématiquement le justificatif."
            )
            description = f"{description} {note_paiement}"
            if "cameroun" in pays.lower():
                actions.insert(0, "Attendre l'autorisation de paiement dans l'espace Études en France, puis suivre les instructions de Campus France Cameroun / TLS selon la procédure.")
            elif "congo" in pays.lower():
                actions.insert(0, "Attendre la demande de paiement de Campus France Congo, puis suivre les instructions indiquées dans l'espace et auprès de l'organisme désigné.")
            actions = actions[:5]

        sources = svc_rag.sources_citees(passages, redige.get("sources") or [])
        # Si le modèle n'a rien cité mais que des passages existent, on
        # rattache quand même le premier : l'étudiant doit pouvoir remonter
        # à la source de ce qu'on lui dit.
        if not sources and passages:
            sources = svc_rag.sources_citees(passages, [1])

        etapes.append(
            EtapeRoadmap(
                ordre=ordre,
                phase=phase,
                titre=str(redige.get("titre") or titre_defaut),
                description=description,
                actions=actions,
                faits=[
                    index_faits[c].to_dict()
                    for c in faits_par_phase.get(phase, [])
                    if c in index_faits
                ],
                sources=sources,
                liens=_liens_pour_phase(profil, phase),
                origine="rag" if sources else "base",
            )
        )
    return etapes


def _resume_secours(profil: Profil) -> str:
    domaine = profil.domaine or "ton domaine"
    niveau = profil.niveau.value if profil.niveau else "master"
    origine = profil.pays_origine or "ton pays"
    return (
        f"Projet de {niveau} en {domaine}, au départ du {origine}. "
        f"La feuille de route ci-dessous suit la procédure Études en France, étape par étape."
    )
