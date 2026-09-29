// i18n.js — Traductions FR/EN + hook + contexte.
//
// Trois principes qui guident la couverture :
//   1. On traduit tout ce qui est écrit à la main dans le front (labels,
//      boutons, écrans marketing, messages courts).
//   2. Le contenu long généré par le back (conversation du conseiller,
//      synthèse de rapport, étapes de la feuille de route) reste dans la
//      langue de génération — le LLM et la base d'établissements ne sont
//      pas encore multilingues. À rouvrir avec un ETL et des prompts EN.
//   3. Sans traduction pour une clé, on retombe sur le français (jamais
//      sur la clé brute), pour ne pas casser l'affichage.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

const CLE_LANG = "onemoov_lang";

export const TRANSLATIONS = {
  fr: {
    // Écran d'accueil (welcome)
    "accueil.eyebrow": "Étudier en France, accompagné.",
    "accueil.titre": "Bienvenue chez One Moov",
    "accueil.sous1": "Votre parcours vers les études en France,",
    "accueil.sous2": "guidé étape par étape.",
    "accueil.creer": "Créer un compte",
    "accueil.connexion": "Se connecter",
    "accueil.legende": "Inscription gratuite · Conseiller Orientation inclus",

    // Header
    "header.dashboard": "← Tableau de bord",
    "header.retour": "← Retour",
    "header.deconnexion": "Déconnexion",
    "header.theme.jour": "Passer en mode clair",
    "header.theme.nuit": "Passer en mode nuit",
    "header.langue": "Langue",

    // Auth
    "auth.titre.creer": "Créer mon compte",
    "auth.titre.connexion": "Se connecter",
    "auth.titre.oublie": "Mot de passe oublié",
    "auth.sous.creer": "Choisis d'abord ton pays de résidence, puis renseigne ton prénom, ton e-mail et ton mot de passe.",
    "auth.sous.autre": "Votre compte vous permet de retrouver vos projets d'un appareil à l'autre.",
    "auth.pays.titre": "Pays de résidence",
    "auth.pays.aide": "Ce choix adapte la procédure Campus France et les opérateurs de paiement mobile disponibles.",
    "auth.pays.chargement": "Chargement des pays…",
    "auth.champ.prenom": "Prénom",
    "auth.champ.email": "E-mail",
    "auth.champ.motdepasse": "Mot de passe",
    "auth.motdepasse.aide": "Au moins 8 caractères, avec une lettre et un chiffre. Une phrase dont tu te souviens vaut mieux qu'un mot compliqué.",
    "auth.bouton.creer": "Créer mon compte",
    "auth.bouton.oublie": "Envoyer le lien",
    "auth.bouton.connexion": "Connexion",
    "auth.deja": "J'ai déjà un compte",
    "auth.pasencore": "Créer un compte",
    "auth.motoublie": "Mot de passe oublié ?",
    "auth.retour.connexion": "Retour à la connexion",
    "auth.err.pays": "Choisis d'abord ton pays de résidence.",
    "auth.err.prenom": "Renseigne ton prénom.",
    "auth.err.email": "Renseigne ton adresse e-mail.",
    "auth.err.motdepasse": "Choisis un mot de passe (8 caractères minimum).",
    "auth.mail.afficher": "Afficher le mot de passe",
    "auth.mail.masquer": "Masquer le mot de passe",
    "auth.verif.titre": "Vérifiez votre e-mail",
    "auth.reset.titre": "Réinitialisation",
    "auth.verif.info": "Votre compte est créé. Confirmez votre adresse pour pouvoir vous connecter.",
    "auth.verif.envoye": "Un e-mail de vérification vous a été envoyé — cliquez le lien qu'il contient.",
    "auth.reset.info": "Suivez le lien pour choisir un nouveau mot de passe.",
    "auth.verif.demo": "Mode démo (aucun e-mail configuré) — utilisez ce lien :",
    "auth.verif.bouton": "Vérifier mon adresse",
    "auth.reset.bouton": "Réinitialiser mon mot de passe",
    "auth.verif.renvoyer": "Renvoyer",
    "auth.verif.jaiverif": "J'ai vérifié — me connecter",

    // Dashboard
    "dash.bonjour": "Bonjour",
    "dash.intro": "Nous vous accompagnons avec efficacité dans votre projet d'études en France : une",
    "dash.gratuit": "orientation gratuite",
    "dash.pistes": "(10 pistes faites pour vous), puis un",
    "dash.parcours": "parcours de mobilité",
    "dash.fin": "pas à pas, de l'admission au voyage.",
    "dash.nouveau": "+ Nouvelle orientation",
    "dash.chargement": "Chargement…",
    "dash.vide": "Vous n'avez pas encore de projet. Lancez votre première orientation, c'est gratuit.",
    "dash.mesprojets": "Mes projets",
    "dash.pistes_proposees": "pistes proposées",
    "dash.voie": "voie",
    "dash.astarter": "Orientation à démarrer",

    // Étapes (chip labels)
    "etape.orientation": "Orientation",
    "etape.formations": "Rapport & pistes",
    "etape.parcours": "Choix du parcours",
    "etape.roadmap": "Feuille de route",

    // Orientation
    "orient.titre": "Conseiller d'orientation",
    "orient.mode.guidee": "Guidée",
    "orient.mode.libre": "Libre",
    "orient.mode.aide.guidee": "Sept questions courtes, ordre fixe. Rapide et prévisible.",
    "orient.mode.aide.libre": "Vraie conversation avec Moov. Plus riche, quelques minutes de plus.",
    "orient.envoyer": "Envoyer",
    "orient.reponse": "Ta réponse…",
    "orient.generer": "✦ Générer mon rapport d'orientation",

    // Rapport
    "rapport.titre": "Votre rapport d'orientation",
    "rapport.profil.titre": "Votre profil, tel que compris",
    "rapport.profil.domaine": "Domaine",
    "rapport.profil.niveau": "Niveau visé",
    "rapport.profil.budget": "Budget annuel",
    "rapport.profil.villes": "Villes visées",
    "rapport.profil.projet": "Projet pro",
    "rapport.atouts": "Vos atouts",
    "rapport.attention": "À travailler",
    "rapport.pistes": "Vos 10 pistes, issues de notre base vérifiée :",
    "rapport.pourquoi": "Pourquoi",
    "rapport.budget.titre": "Estimation budget",
    "rapport.budget.cout_moyen": "Coût annuel moyen des pistes",
    "rapport.budget.cout_min": "Piste la plus abordable",
    "rapport.budget.cout_max": "Piste la plus chère",
    "rapport.budget.total": "Sur 3 ans (frais uniquement)",
    "rapport.budget.confort": "Votre budget déclaré couvre ces formations.",
    "rapport.budget.tendu": "Votre budget est tendu par rapport à ces formations. Prévoyez une bourse ou un financement complémentaire.",
    "rapport.rncp.label": "Code RNCP",
    "rapport.rncp.inconnu": "Code RNCP à vérifier",
    "rapport.formation.cout": "Coût annuel",
    "rapport.formation.non_precise": "non précisé",
    "rapport.suivant": "Passer au parcours de mobilité →",
    "rapport.verifier.titre": "Tu as déjà une école en tête ?",
    "rapport.verifier.aide": "Vérifie que la formation est bien enregistrée au RNCP (titre reconnu par l'État) avant d'aller plus loin.",
    "rapport.verifier.gratuit": "Aucun engagement — c'est gratuit et rapide.",
    "rapport.verifier.bouton": "Vérifier une école & sa formation",
    "rapport.verifier.intitule": "Intitulé de la formation (ex. Master Data Science)",
    "rapport.verifier.etab": "École / établissement (ex. EPITA)",
    "rapport.verifier.code": "Code RNCP si connu (ex. RNCP38363)",
    "rapport.verifier.maintenant": "Vérifier maintenant",
    "rapport.verifier.encours": "Vérification…",
    "rapport.verifier.fermer": "Fermer",
    "rapport.verifier.err_champs": "Renseigne au moins l'intitulé de la formation ou le code RNCP.",
    "rapport.verifier.statut.actif": "✓ Titre reconnu — actif",
    "rapport.verifier.statut.expire": "⚠ Titre expiré",
    "rapport.verifier.statut.deconseille": "⚠ Titre non recommandé",
    "rapport.verifier.statut.indetermine": "ℹ À vérifier auprès de l'école",

    // Parcours
    "parcours.titre": "Parcours de mobilité",
    "parcours.voie": "Votre voie d'accès :",
    "parcours.public": "Public",
    "parcours.prive": "Privé",
    "parcours.mixte": "Les deux",
    "parcours.mixte.aide": "Public et privé menés en parallèle : plus de chances d'admission, la vérification du titre RNCP reste indispensable côté privé.",
    "parcours.rncp.titre": "Vérification du titre RNCP",
    "parcours.rncp.intitule": "Intitulé de la formation",
    "parcours.rncp.etab": "École / établissement",
    "parcours.rncp.code": "Code RNCP si connu (ex. RNCP38363)",
    "parcours.rncp.verifier": "Vérifier le titre",
    "parcours.rncp.verification": "Vérification…",
    "parcours.niveau.titre": "Votre niveau d'entrée",
    "parcours.niveau.aide": "La feuille de route s'adapte à votre niveau (la 1re année passe par la procédure DAP).",
    "parcours.debloquer": "Débloquer le parcours complet",
    "parcours.debloquer.aide": "De l'admission au voyage : feuille de route avec échéances, entretien blanc Campus France, aide à la contestation et assistant.",
    "parcours.payer": "Payer",
    "parcours.jaipaye": "J'ai payé — débloquer ma feuille de route",

    // Roadmap
    "roadmap.titre": "Ma feuille de route",
    "roadmap.avancement": "avancement",
    "roadmap.etapes": "étapes",
    "roadmap.retard": "en retard",
    "roadmap.rentree": "Rentrée visée :",
    "roadmap.prochaine": "Prochaine action",
    "roadmap.echeance": "Échéance conseillée :",
    "roadmap.aides": "Aides IA du parcours",
    "roadmap.entretien": "🎤 Simuler l'entretien Campus France",
    "roadmap.contestation": "📄 Contester un refus",
    "roadmap.arbre": "Arbre",
    "roadmap.liste": "Liste",
    "roadmap.clic": "Cliquez une étape pour le détail",

    // Générique
    "commun.fermer": "Fermer",
    "commun.oui": "Oui",
    "commun.non": "Non",
    "commun.chargement": "Chargement…",
    "commun.erreur": "Erreur",
  },

  en: {
    "accueil.eyebrow": "Study in France, guided all the way.",
    "accueil.titre": "Welcome to One Moov",
    "accueil.sous1": "Your journey to studies in France,",
    "accueil.sous2": "step by step.",
    "accueil.creer": "Create an account",
    "accueil.connexion": "Sign in",
    "accueil.legende": "Free sign-up · Orientation counsellor included",

    "header.dashboard": "← Dashboard",
    "header.retour": "← Back",
    "header.deconnexion": "Sign out",
    "header.theme.jour": "Switch to light mode",
    "header.theme.nuit": "Switch to dark mode",
    "header.langue": "Language",

    "auth.titre.creer": "Create my account",
    "auth.titre.connexion": "Sign in",
    "auth.titre.oublie": "Forgot password",
    "auth.sous.creer": "First choose your country of residence, then enter your first name, email and password.",
    "auth.sous.autre": "Your account lets you find your projects from any device.",
    "auth.pays.titre": "Country of residence",
    "auth.pays.aide": "This choice adapts the Campus France procedure and the mobile money operators available.",
    "auth.pays.chargement": "Loading countries…",
    "auth.champ.prenom": "First name",
    "auth.champ.email": "Email",
    "auth.champ.motdepasse": "Password",
    "auth.motdepasse.aide": "At least 8 characters, with a letter and a digit. A sentence you remember beats a complicated word.",
    "auth.bouton.creer": "Create my account",
    "auth.bouton.oublie": "Send the link",
    "auth.bouton.connexion": "Sign in",
    "auth.deja": "I already have an account",
    "auth.pasencore": "Create an account",
    "auth.motoublie": "Forgot your password?",
    "auth.retour.connexion": "Back to sign in",
    "auth.err.pays": "Please choose your country of residence first.",
    "auth.err.prenom": "Please enter your first name.",
    "auth.err.email": "Please enter your email address.",
    "auth.err.motdepasse": "Please pick a password (at least 8 characters).",
    "auth.mail.afficher": "Show password",
    "auth.mail.masquer": "Hide password",
    "auth.verif.titre": "Verify your email",
    "auth.reset.titre": "Reset your password",
    "auth.verif.info": "Your account is created. Please confirm your address to sign in.",
    "auth.verif.envoye": "A verification email has been sent — click the link inside.",
    "auth.reset.info": "Follow the link to choose a new password.",
    "auth.verif.demo": "Demo mode (no email configured) — use this link:",
    "auth.verif.bouton": "Verify my address",
    "auth.reset.bouton": "Reset my password",
    "auth.verif.renvoyer": "Resend",
    "auth.verif.jaiverif": "I've verified — sign in",

    "dash.bonjour": "Hello",
    "dash.intro": "We help you plan your studies in France step by step: a",
    "dash.gratuit": "free orientation",
    "dash.pistes": "(10 leads picked for you), then a",
    "dash.parcours": "mobility journey",
    "dash.fin": "from admission to the flight.",
    "dash.nouveau": "+ New orientation",
    "dash.chargement": "Loading…",
    "dash.vide": "You have no project yet. Start your first orientation, it's free.",
    "dash.mesprojets": "My projects",
    "dash.pistes_proposees": "leads suggested",
    "dash.voie": "path",
    "dash.astarter": "Orientation to start",

    "etape.orientation": "Orientation",
    "etape.formations": "Report & leads",
    "etape.parcours": "Path choice",
    "etape.roadmap": "Roadmap",

    "orient.titre": "Orientation counsellor",
    "orient.mode.guidee": "Guided",
    "orient.mode.libre": "Free",
    "orient.mode.aide.guidee": "Seven short questions, fixed order. Quick and predictable.",
    "orient.mode.aide.libre": "Real conversation with Moov. Richer, a few more minutes.",
    "orient.envoyer": "Send",
    "orient.reponse": "Your answer…",
    "orient.generer": "✦ Generate my orientation report",

    "rapport.titre": "Your orientation report",
    "rapport.profil.titre": "Your profile, as we understand it",
    "rapport.profil.domaine": "Field",
    "rapport.profil.niveau": "Target level",
    "rapport.profil.budget": "Yearly budget",
    "rapport.profil.villes": "Target cities",
    "rapport.profil.projet": "Career goal",
    "rapport.atouts": "Your strengths",
    "rapport.attention": "To work on",
    "rapport.pistes": "Your 10 leads, from our verified database:",
    "rapport.pourquoi": "Why",
    "rapport.budget.titre": "Budget estimate",
    "rapport.budget.cout_moyen": "Average yearly cost of leads",
    "rapport.budget.cout_min": "Most affordable lead",
    "rapport.budget.cout_max": "Most expensive lead",
    "rapport.budget.total": "Over 3 years (tuition only)",
    "rapport.budget.confort": "Your declared budget covers these programmes.",
    "rapport.budget.tendu": "Your budget is tight against these programmes. Consider a scholarship or extra funding.",
    "rapport.rncp.label": "RNCP code",
    "rapport.rncp.inconnu": "RNCP code to verify",
    "rapport.formation.cout": "Yearly cost",
    "rapport.formation.non_precise": "not specified",
    "rapport.suivant": "Continue to the mobility journey →",
    "rapport.verifier.titre": "Already have a school in mind?",
    "rapport.verifier.aide": "Check that the programme is registered on RNCP (state-recognised title) before going further.",
    "rapport.verifier.gratuit": "No commitment — it's free and fast.",
    "rapport.verifier.bouton": "Check a school & its programme",
    "rapport.verifier.intitule": "Programme name (e.g. Master Data Science)",
    "rapport.verifier.etab": "School / institution (e.g. EPITA)",
    "rapport.verifier.code": "RNCP code if known (e.g. RNCP38363)",
    "rapport.verifier.maintenant": "Check now",
    "rapport.verifier.encours": "Checking…",
    "rapport.verifier.fermer": "Close",
    "rapport.verifier.err_champs": "Please enter at least the programme name or the RNCP code.",
    "rapport.verifier.statut.actif": "✓ Title recognised — active",
    "rapport.verifier.statut.expire": "⚠ Title expired",
    "rapport.verifier.statut.deconseille": "⚠ Title not recommended",
    "rapport.verifier.statut.indetermine": "ℹ To confirm with the school",

    "parcours.titre": "Mobility journey",
    "parcours.voie": "Your access path:",
    "parcours.public": "Public",
    "parcours.prive": "Private",
    "parcours.mixte": "Both",
    "parcours.mixte.aide": "Public and private in parallel: better admission chances, checking the RNCP title remains essential on the private side.",
    "parcours.rncp.titre": "RNCP title check",
    "parcours.rncp.intitule": "Programme name",
    "parcours.rncp.etab": "School / institution",
    "parcours.rncp.code": "RNCP code if known (e.g. RNCP38363)",
    "parcours.rncp.verifier": "Check the title",
    "parcours.rncp.verification": "Checking…",
    "parcours.niveau.titre": "Your entry level",
    "parcours.niveau.aide": "The roadmap adapts to your level (year 1 goes through the DAP procedure).",
    "parcours.debloquer": "Unlock the full journey",
    "parcours.debloquer.aide": "From admission to travel: roadmap with deadlines, Campus France mock interview, appeal help and assistant.",
    "parcours.payer": "Pay",
    "parcours.jaipaye": "I've paid — unlock my roadmap",

    "roadmap.titre": "My roadmap",
    "roadmap.avancement": "progress",
    "roadmap.etapes": "steps",
    "roadmap.retard": "overdue",
    "roadmap.rentree": "Target start:",
    "roadmap.prochaine": "Next action",
    "roadmap.echeance": "Suggested deadline:",
    "roadmap.aides": "AI helpers on this journey",
    "roadmap.entretien": "🎤 Mock Campus France interview",
    "roadmap.contestation": "📄 Appeal a rejection",
    "roadmap.arbre": "Tree",
    "roadmap.liste": "List",
    "roadmap.clic": "Click a step for details",

    "commun.fermer": "Close",
    "commun.oui": "Yes",
    "commun.non": "No",
    "commun.chargement": "Loading…",
    "commun.erreur": "Error",
  },
};

const LangContext = createContext({ lang: "fr", t: (k) => k, setLang: () => {}, basculer: () => {} });

function langeInitiale() {
  try {
    const s = localStorage.getItem(CLE_LANG);
    if (s === "fr" || s === "en") return s;
  } catch { /* localStorage indisponible */ }
  const nav = (typeof navigator !== "undefined" ? navigator.language : "") || "";
  return nav.toLowerCase().startsWith("en") ? "en" : "fr";
}

export function LangProvider({ children }) {
  const [lang, setLang] = useState(langeInitiale);

  useEffect(() => {
    document.documentElement.setAttribute("lang", lang);
    try { localStorage.setItem(CLE_LANG, lang); } catch { /* privé, cleared, etc. */ }
  }, [lang]);

  const t = useCallback((cle) => {
    const table = TRANSLATIONS[lang] || TRANSLATIONS.fr;
    return table[cle] ?? TRANSLATIONS.fr[cle] ?? cle;
  }, [lang]);

  const basculer = useCallback(() => {
    setLang((l) => (l === "fr" ? "en" : "fr"));
  }, []);

  const valeur = useMemo(() => ({ lang, t, setLang, basculer }), [lang, t, basculer]);
  return <LangContext.Provider value={valeur}>{children}</LangContext.Provider>;
}

export function useLang() {
  return useContext(LangContext);
}
