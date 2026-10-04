"""
data/procedures/france.py — Pack procédure « Études en France » (Afrique francophone → France).
De la création du dossier jusqu'à la validation OFII à l'arrivée.

Contenu VÉRIFIÉ à partir de la procédure Campus France / Études en France 2026-2027
(le LLM n'invente pas ces étapes). Les dates exactes varient selon le pays :
`avant_rentree_jours` donne un repère (jours avant la rentrée) que le moteur
d'échéances transforme en date cible et décompte.

- `avant_rentree_jours` : repère négatif = APRÈS la rentrée (ex. validation OFII).
- `critique` : étape « sans filet » — la manquer fait souvent perdre l'année.
- NIVEAUX + ADAPTATIONS : l'entonnoir adapte la procédure au niveau visé
  (L1 = DAP ; L2-L3 / Master / BTS = Hors-DAP).

Ton : VOUVOIEMENT (texte affiché à l'écran).
"""
DATE_VERIF = "2026-09 (procédure Études en France 2026-2027 — à revérifier chaque cycle)"
SOURCE = "Campus France / Études en France · France-Visas · OFII · service-public.fr"

RENTREE_MOIS = 9   # rentrée universitaire de référence (septembre)

# id, label, phase, depends_on, docs, conseil (vérifié), avant_rentree_jours, critique
ETAPES_FRANCE = [
    # ── Phase Candidature ──────────────────────────────────────────
    {"id": "compte", "label": "Créer le dossier « Études en France »", "phase": "Candidature",
     "depends_on": [], "docs": ["Passeport valide", "E-mail permanent", "Téléphone local"],
     "avant_rentree_jours": 305, "critique": False,
     "conseil": "Ouvrez votre compte sur la plateforme « Études en France » de votre pays dès l'ouverture de la campagne (souvent novembre). C'est le point de départ obligatoire."},
    {"id": "langue", "label": "Passer le test de langue (TCF / TEF / DELF)", "phase": "Candidature",
     "depends_on": [], "docs": ["Convocation au test", "Pièce d'identité"],
     "avant_rentree_jours": 290, "critique": False,
     "conseil": "Une certification de français est exigée dès le dépôt du dossier : visez B2 pour une licence, C1 pour un master. Réservez votre session tôt, les places partent vite."},
    {"id": "dossier", "label": "Constituer le dossier", "phase": "Candidature",
     "depends_on": ["compte"], "docs": ["Diplômes + traductions assermentées", "Bulletins des 3 dernières années", "CV", "Lettres de motivation", "Acte de naissance", "Photos"],
     "avant_rentree_jours": 280, "critique": False,
     "conseil": "Rassemblez et numérisez vos pièces. Les traductions assermentées prennent du temps : anticipez."},
    {"id": "voeux", "label": "Déposer vos candidatures / vœux (jusqu'à 7)", "phase": "Candidature",
     "depends_on": ["dossier", "langue"], "docs": ["Dossier complet", "Certification de langue"],
     "avant_rentree_jours": 250, "critique": True,
     "conseil": "Choisissez vos formations (jusqu'à 7 vœux) et déposez-les avant la date limite de votre pays. Échéance stricte : un vœu déposé en retard est perdu."},
    {"id": "frais", "label": "Payer les frais de dossier Campus France", "phase": "Candidature",
     "depends_on": ["voeux"], "docs": ["Justificatif de paiement"],
     "avant_rentree_jours": 245, "critique": True,
     "conseil": "Les frais Campus France (non remboursables) valident votre candidature, souvent sous 48 h après le dépôt. Sans ce paiement, le dossier n'est pas transmis."},
    {"id": "entretien", "label": "Entretien Campus France", "phase": "Candidature",
     "depends_on": ["frais"], "docs": ["Convocation", "Dossier"],
     "avant_rentree_jours": 195, "critique": False,
     "conseil": "Entretien pédagogique (20-30 min) sur votre projet d'études et professionnel. Entraînez-vous : la simulation d'entretien de l'application est là pour ça."},
    {"id": "admission", "label": "Recevoir les réponses d'admission", "phase": "Candidature",
     "depends_on": ["entretien"], "docs": [],
     "avant_rentree_jours": 124, "critique": False,
     "conseil": "Les établissements répondent (souvent avant fin avril). En cas de refus, l'aide à la contestation de l'application vous guide sur les recours réalistes."},
    {"id": "acceptation", "label": "Accepter et confirmer votre inscription", "phase": "Candidature",
     "depends_on": ["admission"], "docs": ["Attestation d'admission", "Frais d'inscription"],
     "avant_rentree_jours": 93, "critique": True,
     "conseil": "Confirmez le vœu choisi avant la date limite (souvent le 31 mai). Sans réponse dans le délai, l'admission peut être annulée automatiquement."},

    # ── Phase Documents (préparation du visa) ──────────────────────
    {"id": "avi", "label": "Preuve de ressources → AVI", "phase": "Documents",
     "depends_on": ["acceptation"], "docs": ["Attestation de virement irrévocable (AVI)"],
     "avant_rentree_jours": 88, "critique": True,
     "conseil": "L'AVI prouve des ressources suffisantes pour l'année (montant minimum fixé par l'État — vérifiez le montant en vigueur sur France-Visas). Passez par un organisme réellement accepté par le consulat ; les délais bancaires surprennent."},
    {"id": "logement", "label": "Attestation de logement", "phase": "Documents",
     "depends_on": ["acceptation"], "docs": ["Attestation de logement / bail"],
     "avant_rentree_jours": 84, "critique": False,
     "conseil": "Attention aux arnaques : ne payez jamais avant une attestation vérifiable. CROUS, Studapart, résidences étudiantes…"},
    {"id": "assurance", "label": "Assurance santé / rapatriement", "phase": "Documents",
     "depends_on": ["acceptation"], "docs": ["Attestation d'assurance"],
     "avant_rentree_jours": 80, "critique": False,
     "conseil": "Souscrivez une assurance conforme aux exigences du visa (couverture, rapatriement)."},

    # ── Phase Visa ─────────────────────────────────────────────────
    {"id": "visa", "label": "Demander le visa long séjour étudiant (VLS-TS)", "phase": "Visa",
     "depends_on": ["acceptation", "avi", "logement", "assurance"],
     "docs": ["Dossier France-Visas", "AVI", "Logement", "Assurance", "Admission", "Passeport"],
     "avant_rentree_jours": 60, "critique": True,
     "conseil": "Déposez votre demande sur France-Visas puis au consulat / VFS. Les créneaux d'été sont rares : prenez rendez-vous très tôt et vérifiez chaque pièce avant l'entretien."},

    # ── Phase Arrivée ──────────────────────────────────────────────
    {"id": "voyage", "label": "Préparer le voyage", "phase": "Arrivée",
     "depends_on": ["visa"], "docs": ["Billet", "Check-list d'arrivée"],
     "avant_rentree_jours": 15, "critique": False,
     "conseil": "Réservez votre billet, préparez vos bagages et votre check-list d'arrivée (logement, banque, premiers papiers)."},
    {"id": "ofii", "label": "Valider votre VLS-TS auprès de l'OFII", "phase": "Arrivée",
     "depends_on": ["voyage"], "docs": ["Formulaire OFII", "Timbre fiscal", "Justificatif de domicile"],
     "avant_rentree_jours": -60, "critique": True,
     "conseil": "Une fois en France, validez votre VLS-TS en ligne auprès de l'OFII dans les 3 mois suivant l'arrivée. Sans validation, votre séjour n'est plus régulier."},
]

# ── Entonnoir par niveau (feature 7) ───────────────────────────────
NIVEAUX = [
    {"id": "l1_dap", "label": "1re année de Licence (L1)",
     "sous_titre": "Procédure DAP — dossier blanc/vert + TCF DAP (dates plus précoces)"},
    {"id": "l2_l3", "label": "Licence 2 / Licence 3",
     "sous_titre": "Procédure Hors-DAP (admission en cours de cursus)"},
    {"id": "master", "label": "Master",
     "sous_titre": "Procédure Hors-DAP / « Mon Master »"},
    {"id": "bts", "label": "BTS / BUT",
     "sous_titre": "Procédure Hors-DAP (candidature établissement)"},
]
NIVEAUX_IDS = {n["id"] for n in NIVEAUX}

# Adaptations : {niveau_id: {etape_id: {champs à écraser}}}
# Cohérence : la DAP ne concerne QUE la L1 (et les écoles d'architecture) ;
# tous les autres niveaux passent par la procédure Hors-DAP.
# ── Entonnoir par domaine ──────────────────────────────────────────
#
# La procédure ne dépend pas que du niveau visé. Deux champs disciplinaires
# relèvent de la Demande d'Admission Préalable quel que soit le discours
# habituel sur « la DAP, c'est la L1 » :
#
#   DAP blanche  L1 à l'université, Y COMPRIS le parcours accès santé
#                (médecine, pharmacie, chirurgie dentaire, maïeutique,
#                masso-kinésithérapie).
#   DAP jaune    les écoles d'architecture, publiques et privées.
#
# Source : Campus France, « Demandes de Licence 1 et écoles d'architecture
# (procédure DAP) », consulté en octobre 2026. Conséquence concrète pour
# l'étudiant : trois vœux au lieu de sept, et une clôture plus précoce.
#
# Deux autres champs gardent la même procédure mais ajoutent une pièce que
# personne ne mentionne avant qu'elle manque : le dossier de travaux en arts
# et design, et le concours ou la plateforme propre des écoles d'ingénieurs
# et de commerce, qui relèvent souvent de l'établissement non connecté.

FAMILLES_DOMAINE = {
    "sante": ["sante", "medecine", "medical", "pharmacie", "dentaire",
              "odontologie", "sage femme", "maieutique", "kinesitherapie",
              "infirmier", "pass", "las"],
    "architecture": ["architecture", "architecte", "ensa", "urbanisme",
                     "paysagiste"],
    "arts": ["arts", "art", "design", "graphisme", "mode", "musique",
             "cinema", "audiovisuel", "spectacle", "beaux arts"],
    "selectif": ["ingenierie", "ingenieur", "commerce", "gestion",
                 "management", "business", "ecole de commerce"],
}


def famille_domaine(domaine: str | None) -> str | None:
    """Rapproche un domaine libre d'une famille de procédure.

    Renvoie None quand le domaine ne change rien à la procédure : c'est le
    cas le plus fréquent, et il ne faut surtout pas inventer une spécificité
    pour le rendre moins banal.
    """
    import unicodedata

    d = unicodedata.normalize("NFD", (domaine or "").lower())
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    # « sage-femme » et « sage femme » doivent se rencontrer : les libellés
    # de domaine arrivent des deux formes selon qu'ils viennent du catalogue
    # ou de l'étudiant.
    d = d.replace("-", " ").replace("'", " ")
    for famille, mots in FAMILLES_DOMAINE.items():
        if any(m in d for m in mots):
            return famille
    return None


# Adaptations par famille de domaine, appliquées APRÈS celles du niveau.
# Même forme que ADAPTATIONS : {etape_id: {champs à écraser}}.
ADAPTATIONS_DOMAINE = {
    "sante": {
        "voeux": {
            "label": "Déposer votre DAP blanche (parcours accès santé)",
            "critique": True,
            "docs": ["Dossier DAP blanche", "TCF DAP", "Diplômes traduits"],
            "conseil": "Le parcours accès santé relève de la DAP, même si on "
                       "vous dit que la DAP ne concerne que la L1. Vous "
                       "formulez trois vœux au lieu de sept, et la clôture "
                       "est plus précoce. Vérifiez le calendrier DAP de "
                       "votre pays, pas le calendrier général.",
        },
        "langue": {
            "label": "Passer le TCF DAP (test spécifique)",
            "conseil": "La DAP exige le TCF DAP, qui n'est pas le TCF tout "
                       "public. Réservez tôt : les sessions sont moins "
                       "nombreuses et la clôture DAP tombe avant les autres.",
        },
    },
    "architecture": {
        "voeux": {
            "label": "Déposer votre DAP jaune (écoles d'architecture)",
            "critique": True,
            "docs": ["Dossier DAP jaune", "TCF DAP", "Dossier de travaux",
                     "Diplômes traduits"],
            "conseil": "Les écoles d'architecture relèvent de la DAP jaune, "
                       "y compris les écoles privées. Trois vœux, clôture "
                       "plus précoce, et la plupart des écoles demandent un "
                       "dossier de travaux personnels.",
        },
        "langue": {
            "label": "Passer le TCF DAP (test spécifique)",
            "conseil": "La DAP exige le TCF DAP. Réservez tôt, les sessions "
                       "sont moins nombreuses.",
        },
        "dossier": {
            "conseil": "Préparez votre dossier de travaux en même temps que "
                       "les pièces administratives : croquis, maquettes "
                       "photographiées, projets personnels. C'est la pièce "
                       "qui demande le plus de temps et celle qu'on "
                       "commence toujours trop tard.",
        },
    },
    "arts": {
        "dossier": {
            "docs": ["Relevés de notes", "Diplômes traduits",
                     "Dossier de travaux (portfolio)"],
            "conseil": "Les formations artistiques demandent presque toutes "
                       "un dossier de travaux, et parfois une épreuve "
                       "pratique. Comptez plusieurs semaines pour le "
                       "constituer : c'est lui qui vous départage, pas le "
                       "relevé de notes.",
        },
    },
    "selectif": {
        "voeux": {
            "conseil": "Beaucoup d'écoles d'ingénieurs et de commerce "
                       "recrutent par concours ou sur leur propre "
                       "plateforme, hors Études en France. Elles relèvent "
                       "alors de la procédure préconsulaire : vous "
                       "candidatez directement auprès de l'école, puis vous "
                       "déclarez l'admission obtenue pour le visa. "
                       "Vérifiez école par école avant de compter sur vos "
                       "vœux Études en France.",
        },
    },
}


ADAPTATIONS = {
    "l1_dap": {
        "langue": {
            "label": "Passer le TCF DAP (test de langue spécifique)",
            "avant_rentree_jours": 300,
            "conseil": "Pour une 1re année, c'est le TCF DAP qui est exigé (test spécifique à la Demande d'Admission Préalable). Réservez-le très tôt : la clôture DAP est plus précoce que les autres niveaux.",
        },
        "dossier": {"avant_rentree_jours": 292},
        "voeux": {
            "label": "Déposer votre DAP (dossier blanc/vert)",
            "avant_rentree_jours": 285,   # DAP : clôture ~mi-décembre, plus tôt
            "docs": ["Dossier DAP", "TCF DAP", "Diplômes traduits"],
            "critique": True,
            "conseil": "En L1 vous passez par la DAP : dossier « blanc » (universités) ou « vert » (écoles d'architecture). La clôture est plus précoce (souvent mi-décembre) — c'est l'échéance à ne pas manquer.",
        },
    },
    "l2_l3": {
        "voeux": {
            "label": "Candidature Hors-DAP (L2 / L3)",
            "conseil": "Hors-DAP : vous candidatez via Études en France sur validation de vos acquis (relevés L1/L2). Soignez le descriptif des crédits déjà obtenus.",
            "docs": ["Relevés de notes détaillés", "Programme des cours suivis", "Certification de langue", "Lettre de motivation"],
        },
    },
    "master": {
        "langue": {
            "conseil": "Pour un master, visez C1 en français (B2 minimum). Certaines mentions exigent un score précis : vérifiez l'attendu de chaque formation.",
        },
        "voeux": {
            "label": "Candidature Master (Hors-DAP / « Mon Master »)",
            "conseil": "En master la sélection est plus forte : projet cohérent avec votre parcours, parfois épreuve ou entretien propre à l'établissement. Visez 2-3 mentions réalistes en plus de vos vœux ambitieux.",
            "docs": ["Diplôme de Licence / attestation", "Relevés de notes", "Projet professionnel", "Lettres de recommandation", "Certification de langue"],
        },
    },
    "bts": {
        "voeux": {
            "label": "Candidature BTS / BUT (Hors-DAP)",
            "conseil": "Pour un BTS/BUT, la candidature passe par Études en France (souvent en lien direct avec l'établissement pour l'international). Contactez tôt les établissements visés pour confirmer la voie d'entrée.",
            "docs": ["Baccalauréat / attestation", "Relevés de notes", "Certification de langue", "Lettre de motivation"],
        },
    },
}
