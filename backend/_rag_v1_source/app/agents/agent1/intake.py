"""Agent 1, étape 1 : l'intake.

Transforme le récit libre de l'étudiant en un profil structuré et validé.
Deux modes :

    guidée   l'agent pose les questions dans un ordre fixe, avec des réponses
             proposées. Rapide, prévisible, et fonctionne sans modèle.
    libre    l'étudiant raconte son projet, l'agent extrait ce qu'il peut et
             relance sur ce qui manque.

La sortie passe systématiquement par le contrat Pydantic. Si le modèle
renvoie « Maîtrise » là où le contrat attend « master », la valeur est
rejetée plutôt que propagée.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.models.schemas import (
    Profil, ReponseOrientation, RequeteOrientation, ModeConversation,
    Niveau, Formation,
)
from app.services.llm import chat_json, ErreurLLM, ModeMock

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Parcours guidé
# --------------------------------------------------------------------------

ETAPES_GUIDEES = [
    {
        "champ": "domaine",
        "question": "Quel domaine veux-tu étudier ?",
        "suggestions": ["Informatique et IA", "Commerce et gestion", "Droit", "Ingénierie", "Santé"],
    },
    {
        "champ": "niveau",
        "question": "Tu vises quel niveau ?",
        "suggestions": ["Licence", "Master", "Doctorat"],
    },
    {
        "champ": "formation",
        "question": "Quel type de formation ?",
        "suggestions": ["Initiale", "Alternance", "Continue"],
    },
    {
        "champ": "budget_mensuel",
        "question": "Quel budget mensuel peux-tu consacrer à ta vie sur place ?",
        "suggestions": ["Moins de 600 €", "600 à 800 €", "800 à 1000 €", "Plus de 1000 €"],
    },
    {
        "champ": "pays_origine",
        "question": "De quel pays pars-tu ?",
        "suggestions": ["Cameroun", "Congo-Brazzaville"],
    },
    {
        "champ": "projet_etudes",
        "question": "Décris ton projet d'études en une phrase.",
        "suggestions": [],
    },
    {
        "champ": "projet_pro",
        "question": "Et après ton diplôme, quel métier vises-tu, et où ?",
        "suggestions": [],
    },
]

# Correspondances entre ce que l'étudiant écrit et les valeurs du contrat.
_NIVEAUX = {
    "licence": Niveau.licence, "bachelor": Niveau.licence, "l3": Niveau.licence,
    "master": Niveau.master, "maîtrise": Niveau.master, "maitrise": Niveau.master,
    "m1": Niveau.master, "m2": Niveau.master, "bac+5": Niveau.master,
    "doctorat": Niveau.doctorat, "thèse": Niveau.doctorat, "these": Niveau.doctorat,
    "phd": Niveau.doctorat,
}

_FORMATIONS = {
    "initiale": Formation.initiale, "classique": Formation.initiale,
    "alternance": Formation.alternance, "apprentissage": Formation.alternance,
    "continue": Formation.continue_, "formation continue": Formation.continue_,
}




# Nettoyage léger des textes de projet. L'objectif est de corriger les
# erreurs de frappe/ponctuation évidentes sans réécrire le fond du projet.
_REPARATIONS_TEXTE = {
    "etudes": "études",
    "etude": "étude",
    "developpement": "développement",
    "developper": "développer",
    "diplome": "diplôme",
    "metier": "métier",
    "projet professionnel": "projet professionnel",
    "reussir": "réussir",
    "reussite": "réussite",
    "experience": "expérience",
    "formation professionnelle": "formation professionnelle",
    "informatique et ia": "Informatique et IA",
    "intelligence artificielle": "intelligence artificielle",
}


def _nettoyer_texte_projet(texte: str | None) -> str | None:
    """Nettoie une phrase de projet sans en modifier le sens."""
    if not texte:
        return None
    import re

    value = re.sub(r"\s+", " ", str(texte).replace("\u00a0", " ")).strip()
    if not value:
        return None

    # Corrections ciblées, insensibles à la casse, uniquement sur des mots.
    for source, cible in _REPARATIONS_TEXTE.items():
        value = re.sub(rf"\b{re.escape(source)}\b", cible, value, flags=re.IGNORECASE)

    # Ponctuation française : pas d'espace avant ,.;:!? et une phrase fermée.
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    value = re.sub(r"([,;:])(?=\S)", r"\1 ", value)
    if value and value[-1] not in ".!?":
        value += "."
    value = value[0].upper() + value[1:]
    return value[:600]


def _lire_niveau(valeur: str) -> Optional[Niveau]:
    v = (valeur or "").strip().lower()
    for cle, niveau in _NIVEAUX.items():
        if cle in v:
            return niveau
    return None


def _lire_formation(valeur: str) -> Optional[Formation]:
    v = (valeur or "").strip().lower()
    for cle, formation in _FORMATIONS.items():
        if cle in v:
            return formation
    return None


def _lire_budget(valeur: str) -> Optional[int]:
    """Extrait un montant d'une réponse écrite librement."""
    import re

    v = (valeur or "").lower()
    nombres = [int(n) for n in re.findall(r"\d+", v.replace(" ", ""))]
    if not nombres:
        return None
    if "moins" in v:
        return nombres[0] - 50 if nombres[0] > 100 else nombres[0]
    if "plus" in v:
        return nombres[0] + 100
    if len(nombres) >= 2:          # « 600 à 800 » : on prend le milieu
        return (nombres[0] + nombres[1]) // 2
    return nombres[0]


def _appliquer(profil: Profil, champ: str, valeur: str) -> Profil:
    """Enregistre une réponse sur le bon champ, après conversion."""
    donnees = profil.model_dump()

    if champ == "niveau":
        lu = _lire_niveau(valeur)
        if lu:
            donnees["niveau"] = lu
    elif champ == "formation":
        lu = _lire_formation(valeur)
        if lu:
            donnees["formation"] = lu
    elif champ == "budget_mensuel":
        lu = _lire_budget(valeur)
        if lu:
            donnees["budget_mensuel"] = lu
    else:
        if champ in {"projet_etudes", "projet_pro"}:
            donnees[champ] = _nettoyer_texte_projet(valeur)
        else:
            donnees[champ] = valeur.strip()[:600]

    return Profil(**donnees)


def intake_guide_lot(reponses: dict[str, str]) -> ReponseOrientation:
    """Applique en un seul appel les sept réponses du parcours guidé.

    Pourquoi cette route existe
    ---------------------------
    Le parcours guidé est la seule partie des agents qui fonctionne sans
    modèle : sept questions dans un ordre fixe. Le client peut donc les poser
    hors ligne, avec la liste qu'il a mise en cache, puis faire valider les
    sept réponses d'un coup au retour du réseau.

    La validation reste ici et non dans le navigateur. « Maîtrise », « bac+5 »
    et « M2 » désignent le même niveau, et la table de correspondance qui le
    sait vit à côté du contrat Pydantic qu'elle doit satisfaire. La dupliquer
    en JavaScript garantirait qu'elles divergent.
    """
    profil = Profil()
    for etape in ETAPES_GUIDEES:
        valeur = reponses.get(etape["champ"])
        if valeur and str(valeur).strip():
            profil = _appliquer(profil, etape["champ"], str(valeur))

    suivant = _champ_manquant(profil)
    if suivant is None:
        return ReponseOrientation(
            message="Ton projet est clair. Tu peux générer ta feuille de route.",
            profil=profil,
            suggestions=[],
            complet=True,
        )

    return ReponseOrientation(
        message=suivant["question"],
        profil=profil,
        suggestions=suivant["suggestions"],
        complet=False,
        champ_attendu=suivant["champ"],
    )


def _champ_manquant(profil: Profil) -> Optional[dict]:
    donnees = profil.model_dump()
    for etape in ETAPES_GUIDEES:
        if not donnees.get(etape["champ"]):
            return etape
    return None


def intake_guide(requete: RequeteOrientation) -> ReponseOrientation:
    """Parcours guidé, sans appel au modèle.

    Rapide, prévisible, et disponible même si le fournisseur est en panne.
    C'est le mode par défaut pour la majorité des étudiants.
    """
    profil = requete.profil

    # Le message répond à la question en cours, donc au premier champ vide.
    if requete.message.strip():
        en_cours = _champ_manquant(profil)
        if en_cours:
            profil = _appliquer(profil, en_cours["champ"], requete.message)

    suivant = _champ_manquant(profil)

    if suivant is None:
        return ReponseOrientation(
            message="Ton projet est clair. Tu peux générer ta feuille de route.",
            profil=profil,
            suggestions=[],
            complet=True,
        )

    return ReponseOrientation(
        message=suivant["question"],
        profil=profil,
        suggestions=suivant["suggestions"],
        complet=False,
        champ_attendu=suivant["champ"],
    )


# --------------------------------------------------------------------------
# Conversation libre
# --------------------------------------------------------------------------

SYSTEME_LIBRE = """Tu es l'agent d'orientation de One Moov. Tu accompagnes des étudiants d'Afrique centrale, principalement du Cameroun et du Congo-Brazzaville, qui préparent des études en France.

Ton rôle dans cet échange : comprendre le projet de l'étudiant en conversation naturelle, et remplir progressivement son profil.

Informations à réunir : domaine d'études, niveau visé, type de formation, budget de vie mensuel en euros, pays de départ, projet d'études en une phrase, projet professionnel.

Règles :
- Tutoie, sois chaleureux et bref. Une seule question à la fois.
- Ne redemande jamais une information déjà présente dans le profil.
- Tu n'annonces AUCUN montant de frais, aucune date limite et aucun quota d'heures. Ces valeurs viennent de sources officielles vérifiées, pas de toi.
- Le niveau doit valoir exactement licence, master, doctorat ou autre.
- La formation doit valoir exactement initiale, alternance ou continue.
- Le budget est un nombre entier en euros.
- Reformule légèrement « projet_etudes » et « projet_pro » dans un français propre : corrige les fautes de frappe, les accents et la ponctuation sans changer le sens ni inventer d'information.

Réponds UNIQUEMENT en JSON, sans texte autour :
{
  "message": "ta réponse à l'étudiant",
  "profil": {"domaine": "...", "niveau": "master", "formation": "initiale", "budget_mensuel": 800, "pays_origine": "...", "projet_etudes": "...", "projet_pro": "..."},
  "suggestions": ["réponse rapide", "autre"],
  "complet": false
}

Le champ profil reprend toutes les informations connues, anciennes et nouvelles. Omets les champs inconnus."""


def intake_libre(requete: RequeteOrientation) -> ReponseOrientation:
    """Conversation libre, portée par le modèle.

    En cas d'indisponibilité du fournisseur, on retombe sur le parcours
    guidé plutôt que d'afficher une erreur à l'étudiant.
    """
    profil = requete.profil

    contexte = [
        "Profil connu à ce stade :",
        profil.model_dump_json(indent=2, exclude_none=True),
        "",
        "Échange précédent :",
        "\n".join(
            f"{'Étudiant' if m.role == 'etudiant' else 'Agent'} : {m.texte}"
            for m in requete.historique[-8:]
        ) or "(début de l'échange)",
        "",
        f"Nouveau message : {requete.message or '(il vient d''ouvrir la conversation)'}",
    ]

    try:
        brut = chat_json(SYSTEME_LIBRE, "\n".join(contexte), temperature=0.4, max_tokens=900,
                          fonction="orientation")
    except (ModeMock, ErreurLLM) as e:
        if isinstance(e, ErreurLLM):
            logger.warning("Bascule sur le parcours guidé : %s", e)
        return intake_guide(requete)

    # La sortie du modèle passe par le contrat : ce qui ne respecte pas
    # les valeurs attendues est écarté, champ par champ.
    fusion = profil.model_dump()
    for champ, valeur in (brut.get("profil") or {}).items():
        if champ not in fusion or valeur in (None, "", []):
            continue
        if champ == "niveau":
            lu = _lire_niveau(str(valeur))
            if lu:
                fusion[champ] = lu
        elif champ == "formation":
            lu = _lire_formation(str(valeur))
            if lu:
                fusion[champ] = lu
        elif champ == "budget_mensuel":
            lu = _lire_budget(str(valeur))
            if lu:
                fusion[champ] = lu
        else:
            if champ in {"projet_etudes", "projet_pro"}:
                fusion[champ] = _nettoyer_texte_projet(str(valeur))
            else:
                fusion[champ] = str(valeur).strip()[:600]

    try:
        profil_maj = Profil(**fusion)
    except Exception:  # noqa: BLE001
        logger.warning("Profil invalide renvoyé par le modèle, on garde l'ancien")
        profil_maj = profil

    return ReponseOrientation(
        message=str(brut.get("message") or "Peux-tu m'en dire un peu plus ?"),
        profil=profil_maj,
        suggestions=[str(s) for s in (brut.get("suggestions") or [])][:4],
        complet=profil_maj.est_complet(),
    )


def traiter(requete: RequeteOrientation) -> ReponseOrientation:
    if requete.mode == ModeConversation.libre:
        return intake_libre(requete)
    return intake_guide(requete)
