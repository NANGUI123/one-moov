import { useState, useEffect, useRef } from "react";
import { api, getToken, setToken } from "./api.js";
import { C, URG, CLE_THEME } from "./styles.js";

// ── Thème (blanc + vert par défaut, bascule mode nuit) ─────────────
//
// Trois états possibles : « light », « dark », ou aucune préférence
// enregistrée — auquel cas on suit `prefers-color-scheme`. On stocke
// l'explicite dans localStorage pour que le choix survive à la fermeture
// et voyage d'un onglet à l'autre.
function themeCourant() {
  try {
    const t = localStorage.getItem(CLE_THEME);
    if (t === "light" || t === "dark") return t;
  } catch { /* localStorage indisponible : on lit prefers-color-scheme */ }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function useTheme() {
  const [theme, setThemeState] = useState(themeCourant);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem(CLE_THEME, theme); } catch { /* privé, cleared, etc. */ }
  }, [theme]);

  return [theme, () => setThemeState((t) => (t === "dark" ? "light" : "dark"))];
}

function IconeSoleil() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  );
}
function IconeLune() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

function ThemeToggle({ theme, onToggle }) {
  const suivant = theme === "dark" ? "Passer en mode clair" : "Passer en mode nuit";
  return (
    <button className="theme-toggle" onClick={onToggle}
      aria-label={suivant} title={suivant}>
      {theme === "dark" ? <IconeSoleil /> : <IconeLune />}
    </button>
  );
}

// Transparence (feature 2) — texte statique (vouvoiement), aligné sur le backend.
const TRANSPARENCE = {
  titre: "Comment ces pistes sont trouvées",
  principe: "Les formations viennent de notre base vérifiée — jamais inventées par l'IA. Le classement suit des règles explicites :",
  etapes: [
    "Nous lisons votre profil (domaine, niveau, budget, ville, projet pro) issu de l'entretien.",
    "Nous interrogeons notre base alimentée par l'open data public (ONISEP / Mon Master / Parcoursup).",
    "Un score déterministe classe chaque formation : domaine (40), niveau (25), budget (20), ville (12), voie (6).",
    "L'IA ne choisit ni n'invente aucune école : elle présente le résultat. Chaque piste dit pourquoi elle est là.",
  ],
};

const ETAPE_LABEL = { orientation: "Orientation", formations: "Rapport & pistes", parcours: "Choix du parcours", roadmap: "Feuille de route" };
const viewForEtape = (e) => (e === "roadmap" ? "roadmap" : e === "parcours" ? "parcours" : e === "formations" ? "rapport" : "orientation");
const decompte = (j) => (j == null ? "" : j < 0 ? `en retard de ${-j} j` : j === 0 ? "aujourd'hui" : `dans ${j} j`);
const fcfa = (n) => `${(n || 0).toLocaleString("fr-FR").replace(/ /g, " ")} FCFA`;
const PRIX_FCFA = 52477;

export default function App() {
  // welcome = écran d'accueil marketing ; auth = inscription/connexion ;
  // le reste = écrans applicatifs après connexion.
  const [view, setView] = useState("welcome");
  const [authMode, setAuthMode] = useState("register"); // "register" | "login"
  const [prenom, setPrenom] = useState("");
  const [piste, setPiste] = useState(null);
  const [rapport, setRapport] = useState(null);
  const [theme, toggleTheme] = useTheme();

  useEffect(() => {
    if (getToken()) api.me().then((u) => { setPrenom(u.prenom || ""); setView("dashboard"); }).catch(() => setToken(null));
  }, []);

  const logout = () => { setToken(null); setPiste(null); setRapport(null); setView("welcome"); };
  const goDash = () => { setPiste(null); setRapport(null); setView("dashboard"); };

  const openPiste = async (id) => {
    const p = await api.getPiste(id);
    setPiste(p);
    setView(viewForEtape(
      p.paid ? "roadmap" : p.voie ? "parcours" : (p.formations || []).length ? "formations" : "orientation"));
  };

  // Écran d'accueil : plein écran, dégradé fixe, pas de header en dur.
  if (view === "welcome") {
    return <Accueil
      onRegister={() => { setAuthMode("register"); setView("auth"); }}
      onLogin={() => { setAuthMode("login"); setView("auth"); }}
    />;
  }

  return (
    <div className="wrap">
      <Header prenom={prenom} theme={theme} onToggleTheme={toggleTheme}
        onHome={view !== "auth" && view !== "dashboard" ? goDash : null}
        onBack={view === "auth" ? () => setView("welcome") : null}
        onLogout={view !== "auth" ? logout : null} />
      {view === "auth" && <Auth initialMode={authMode}
        onAuth={(p) => { setPrenom(p); setView("dashboard"); }} />}
      {view === "dashboard" && <Dashboard prenom={prenom}
        onNew={async () => { setPiste(await api.createPiste("Cameroun")); setRapport(null); setView("orientation"); }}
        onOpen={openPiste} />}
      {view === "orientation" && <Orientation piste={piste} prenom={prenom}
        onDone={(rap, pi) => { setRapport(rap); setPiste(pi); setView("rapport"); }} />}
      {view === "rapport" && <Rapport piste={piste} rapport={rapport} onNext={() => setView("parcours")} />}
      {view === "parcours" && <Parcours piste={piste} onPaid={(pi) => { setPiste(pi); setView("roadmap"); }} />}
      {view === "roadmap" && <Roadmap piste={piste} prenom={prenom} />}
    </div>
  );
}

function Header({ prenom, onHome, onLogout, onBack, theme, onToggleTheme }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18, gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
        <div style={{ fontFamily: "Poppins", fontWeight: 700, fontSize: 20, color: C.teal, cursor: onHome ? "pointer" : "default" }}
          onClick={onHome || undefined}>One Moov</div>
        {onHome && <span className="link" onClick={onHome} style={{ fontSize: 13 }}>← Tableau de bord</span>}
        {onBack && <span className="link" onClick={onBack} style={{ fontSize: 13 }}>← Retour</span>}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
        {onToggleTheme && <ThemeToggle theme={theme} onToggle={onToggleTheme} />}
        {onLogout && <button className="btn-ghost btn-sm" onClick={onLogout}>Déconnexion</button>}
      </div>
    </div>
  );
}

// ── Écran d'accueil (avant l'inscription/connexion) ────────────────
function Accueil({ onRegister, onLogin }) {
  return (
    <div className="accueil">
      <div className="accueil-marque">
        <div className="accueil-logo" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="16" cy="16" r="10" />
            <path d="M11 16h10M16 11v10" />
          </svg>
        </div>
        <div className="accueil-marque-nom">one moov</div>
      </div>

      <div className="accueil-contenu">
        <div className="accueil-corps">
          <div className="accueil-eyebrow">Étudier en France, accompagné.</div>
          <h1 className="accueil-titre">Bienvenue chez One Moov</h1>
          <p className="accueil-sous">
            Votre parcours vers les études en France,<br />guidé étape par étape.
          </p>
        </div>

        <div className="accueil-actions">
          <button className="accueil-btn primaire" onClick={onRegister}>Créer un compte</button>
          <button className="accueil-btn secondaire" onClick={onLogin}>Se connecter</button>
          <div className="accueil-legende">Inscription gratuite · Conseiller Orientation inclus</div>
        </div>
      </div>
    </div>
  );
}

// ── Authentification (inscription + vérification e-mail + reset) ───
function Auth({ onAuth, initialMode = "register" }) {
  const [mode, setMode] = useState(initialMode);   // register | login | forgot
  const [email, setEmail] = useState(""); const [pw, setPw] = useState(""); const [pn, setPn] = useState("");
  const [pays, setPays] = useState("");           // Cameroun | Congo-Brazzaville | ""
  const [voirPw, setVoirPw] = useState(false);    // toggle œil sur le mot de passe
  const [err, setErr] = useState(""); const [info, setInfo] = useState(""); const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(null);   // {email, demo_lien, envoye} après inscription
  const [unverified, setUnverified] = useState(false);
  const [paysDispo, setPaysDispo] = useState(null);  // liste chargée depuis l'API

  // Pays chargés en une fois : la liste est petite et servie sans jeton.
  // Un repli local est armé après 3 s pour ne pas laisser l'étudiant devant
  // « Chargement… » quand le back Render dort ou n'est pas joignable — la
  // sélection reste utilisable en toutes circonstances.
  useEffect(() => {
    if (mode !== "register") return;
    const REPLI = [
      { code: "Cameroun", libelle: "Cameroun", campus_france: "Campus France Cameroun", drapeau: "🇨🇲" },
      { code: "Congo-Brazzaville", libelle: "Congo-Brazzaville", campus_france: "Campus France Congo", drapeau: "🇨🇬" },
    ];
    let annule = false;
    const timer = setTimeout(() => { if (!annule) setPaysDispo(REPLI); }, 3000);
    api.paysDisponibles()
      .then((d) => { if (!annule) { clearTimeout(timer); setPaysDispo(d.pays); } })
      .catch(() => { if (!annule) { clearTimeout(timer); setPaysDispo(REPLI); } });
    return () => { annule = true; clearTimeout(timer); };
  }, [mode]);

  const reset = () => { setErr(""); setInfo(""); };

  const submitRegister = async () => {
    reset();
    // On vérifie chaque champ dans l'ordre du formulaire et on renvoie un
    // message précis. Silencer un clic parce qu'un champ manque déroute
    // l'étudiant : « pourquoi rien ne se passe ? ».
    if (!pays) { setErr("Choisis d'abord ton pays de résidence."); return; }
    if (!pn.trim()) { setErr("Renseigne ton prénom."); return; }
    if (!email.trim()) { setErr("Renseigne ton adresse e-mail."); return; }
    if (!pw) { setErr("Choisis un mot de passe (8 caractères minimum)."); return; }
    setBusy(true);
    try {
      const r = await api.register(email, pw, pn, pays);
      if (r.access_token) { setToken(r.access_token); onAuth(r.prenom || pn); return; }
      setPending({ email: r.email, demo_lien: r.demo_lien, envoye: r.envoye });
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const submitLogin = async () => {
    reset(); setUnverified(false); setBusy(true);
    try { const r = await api.login(email, pw); setToken(r.access_token); onAuth(r.prenom || ""); }
    catch (e) { setErr(e.message); if (/vérif/i.test(e.message)) setUnverified(true); setBusy(false); }
  };
  const resend = async () => {
    reset(); try { const r = await api.resendVerif(email); setInfo(r.demo_lien ? "Lien régénéré ci-dessous (mode démo)." : "E-mail renvoyé."); if (r.demo_lien) setPending({ email, demo_lien: r.demo_lien, envoye: r.envoye }); }
    catch (e) { setErr(e.message); }
  };
  const submitForgot = async () => {
    reset(); setBusy(true);
    try { const r = await api.forgot(email); setInfo(r.demo_lien ? "Lien de réinitialisation ci-dessous (mode démo)." : "Si un compte existe, un e-mail vient d'être envoyé."); setPending(r.demo_lien ? { email, demo_lien: r.demo_lien, reset: true } : null); }
    catch (e) { setErr(e.message); }
    setBusy(false);
  };

  // Écran « vérifiez votre e-mail »
  if (pending) {
    return (
      <div className="card">
        <h2 style={{ marginTop: 0 }}>{pending.reset ? "Réinitialisation" : "Vérifiez votre e-mail"}</h2>
        <p>{pending.reset
          ? "Suivez le lien pour choisir un nouveau mot de passe."
          : <>Votre compte est créé. {pending.envoye ? "Un e-mail de vérification vous a été envoyé — cliquez le lien qu'il contient." : "Confirmez votre adresse pour pouvoir vous connecter."}</>}</p>
        {pending.demo_lien && (
          <div className="card card-soft" style={{ marginBottom: 12 }}>
            <div className="muted" style={{ marginBottom: 6 }}>Mode démo (aucun e-mail configuré) — utilisez ce lien :</div>
            <a className="btn" style={{ display: "inline-block", textDecoration: "none" }} href={pending.demo_lien} target="_blank" rel="noreferrer">
              {pending.reset ? "Réinitialiser mon mot de passe" : "Vérifier mon adresse"}
            </a>
          </div>
        )}
        {!pending.reset && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="btn-ghost btn-sm" onClick={resend}>Renvoyer</button>
            <button className="btn btn-sm" onClick={() => { setPending(null); setMode("login"); }}>J'ai vérifié — me connecter</button>
          </div>
        )}
        {pending.reset && <button className="btn btn-sm" onClick={() => { setPending(null); setMode("login"); }}>Retour à la connexion</button>}
        {info && <div className="muted" style={{ marginTop: 8 }}>{info}</div>}
      </div>
    );
  }

  // On ne désactive le bouton que pendant l'appel en cours. Les champs
  // manquants sont signalés par un message clair au clic (submitRegister),
  // pas par un bouton silencieusement grisé qui laisse l'étudiant perplexe.

  return (
    <div className="card">
      <h2 style={{ marginTop: 0, textAlign: "center" }}>
        {mode === "register" ? "Créer mon compte" : mode === "forgot" ? "Mot de passe oublié" : "Se connecter"}
      </h2>
      {mode === "register" && (
        <p className="muted" style={{ textAlign: "center", marginTop: 0 }}>
          Choisis d'abord ton pays de résidence, puis renseigne ton prénom, ton e-mail et ton mot de passe.
        </p>
      )}
      {mode !== "register" && (
        <p className="muted" style={{ textAlign: "center", marginTop: 0 }}>
          Votre compte vous permet de retrouver vos projets d'un appareil à l'autre.
        </p>
      )}

      {mode === "register" && (
        <>
          <div style={{ fontWeight: 600, color: C.ink, marginTop: 8, marginBottom: 4 }}>Pays de résidence</div>
          <div className="muted" style={{ marginBottom: 8 }}>
            Ce choix adapte la procédure Campus France et les opérateurs de paiement mobile disponibles.
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 12 }}>
            {(paysDispo || []).map((p) => (
              <CartePays key={p.code} pays={p} choisi={pays === p.code} onClick={() => setPays(p.code)} />
            ))}
            {paysDispo === null && <div className="muted">Chargement des pays…</div>}
          </div>
        </>
      )}

      {mode === "register" && (
        <input className="inp" placeholder="Prénom" value={pn} onChange={(e) => setPn(e.target.value)} />
      )}
      <input className="inp" placeholder="E-mail" type="email" autoComplete="email"
        value={email} onChange={(e) => setEmail(e.target.value)} />

      {mode !== "forgot" && (
        <>
          <div style={{ position: "relative" }}>
            <input className="inp" type={voirPw ? "text" : "password"} placeholder="Mot de passe"
              autoComplete={mode === "register" ? "new-password" : "current-password"}
              value={pw}
              onChange={(e) => setPw(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && (mode === "register" ? submitRegister() : submitLogin())}
              style={{ paddingRight: 42 }} />
            <button type="button" onClick={() => setVoirPw((v) => !v)}
              aria-label={voirPw ? "Masquer le mot de passe" : "Afficher le mot de passe"}
              style={{
                position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)",
                background: "transparent", border: 0, color: C.muted, cursor: "pointer",
                padding: 8, display: "flex", alignItems: "center",
              }}>
              {voirPw ? <IconeOeilBarre /> : <IconeOeil />}
            </button>
          </div>
          {mode === "register" && (
            <div className="muted" style={{ marginTop: 4 }}>
              Au moins 8 caractères, avec une lettre et un chiffre. Une phrase dont tu te souviens vaut mieux qu'un mot compliqué.
            </div>
          )}
        </>
      )}

      {err && <div style={{ color: C.danger, fontSize: 13, margin: "6px 0" }}>{err}</div>}
      {unverified && <div className="muted" style={{ margin: "4px 0" }}><span className="link" onClick={resend}>Renvoyer l'e-mail de vérification</span></div>}
      {info && <div className="muted" style={{ margin: "6px 0" }}>{info}</div>}

      <button className="btn" disabled={busy} style={{ width: "100%", marginTop: 10 }}
        onClick={mode === "register" ? submitRegister : mode === "forgot" ? submitForgot : submitLogin}>
        {busy ? "…" : (mode === "register" ? "Créer mon compte" : mode === "forgot" ? "Envoyer le lien" : "Connexion")}
      </button>

      <div style={{ marginTop: 14, textAlign: "center", display: "flex", flexDirection: "column", gap: 8 }}>
        <span className="link muted" onClick={() => { reset(); setMode(mode === "register" ? "login" : "register"); }}>
          {mode === "register" ? "J'ai déjà un compte" : "Créer un compte"}
        </span>
        {mode === "login" && <span className="link muted" onClick={() => { reset(); setMode("forgot"); }}>Mot de passe oublié ?</span>}
        {mode === "forgot" && <span className="link muted" onClick={() => { reset(); setMode("login"); }}>Retour à la connexion</span>}
      </div>
    </div>
  );
}

function CartePays({ pays, choisi, onClick }) {
  return (
    <button type="button" onClick={onClick}
      aria-pressed={choisi}
      style={{
        display: "flex", alignItems: "center", gap: 12, textAlign: "left",
        background: choisi ? "var(--teal-soft)" : "var(--surface)",
        border: `1.5px solid ${choisi ? "var(--teal)" : "var(--line)"}`,
        borderRadius: 12, padding: "12px 14px", cursor: "pointer",
        transition: "border-color .15s, background-color .15s",
        width: "100%",
      }}>
      <span style={{ fontSize: 28, lineHeight: 1 }} aria-hidden="true">{pays.drapeau}</span>
      <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
        <span style={{ fontWeight: 700, color: C.ink }}>{pays.libelle}</span>
        <span className="muted" style={{ fontSize: 12 }}>{pays.campus_france}</span>
      </span>
      {choisi && <span aria-hidden="true" style={{ marginLeft: "auto", color: C.teal, fontWeight: 700 }}>✓</span>}
    </button>
  );
}

function IconeOeil() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}
function IconeOeilBarre() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a19.6 19.6 0 0 1 5.06-5.94" />
      <path d="M9.9 4.24A10.94 10.94 0 0 1 12 4c7 0 11 8 11 8a19.5 19.5 0 0 1-3.17 4.19" />
      <path d="M14.12 14.12A3 3 0 0 1 9.88 9.88" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  );
}

// ── Tableau de bord (feature 14) ───────────────────────────────────
function Dashboard({ prenom, onNew, onOpen }) {
  const [pistes, setPistes] = useState(null);
  useEffect(() => { api.listPistes().then((d) => setPistes(d.pistes)).catch(() => setPistes([])); }, []);

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>Bonjour {prenom || ""} 👋</h1>
      <p style={{ marginTop: 0 }}>Nous vous accompagnons avec efficacité dans votre projet d'études en France :
        une <b>orientation gratuite</b> (10 pistes faites pour vous), puis un <b>parcours de mobilité</b> pas à pas,
        de l'admission au voyage.</p>
      <button className="btn" onClick={onNew} style={{ width: "100%", marginBottom: 16 }}>+ Nouvelle orientation</button>

      {pistes === null && <p className="muted">Chargement…</p>}
      {pistes && pistes.length === 0 && (
        <div className="card card-soft"><p className="muted" style={{ margin: 0 }}>Vous n'avez pas encore de projet. Lancez votre première orientation, c'est gratuit.</p></div>
      )}
      {pistes && pistes.length > 0 && <div className="muted" style={{ marginBottom: 6 }}>Mes projets</div>}
      {pistes && pistes.map((p) => (
        <div className="card" key={p.id} style={{ cursor: "pointer" }} onClick={() => onOpen(p.id)}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
            <div style={{ fontWeight: 700 }}>{p.titre} <span className="muted" style={{ fontWeight: 400 }}>· {p.pays}</span></div>
            <span className="chip" style={{ margin: 0 }}>{ETAPE_LABEL[p.etape]}</span>
          </div>
          {p.paid && (
            <>
              <div className="progress"><i style={{ width: `${p.progression_pct}%` }} /></div>
              <div className="muted" style={{ display: "flex", justifyContent: "space-between" }}>
                <span>{p.progression_pct}% · prochaine : {p.prochaine_action || "—"}{p.prochaine_echeance ? ` (${p.prochaine_echeance})` : ""}</span>
                {p.nb_en_retard > 0 && <span style={{ color: C.danger }}>{p.nb_en_retard} en retard</span>}
              </div>
            </>
          )}
          {!p.paid && <div className="muted">{p.nb_formations ? `${p.nb_formations} pistes proposées` : "Orientation à démarrer"}{p.voie ? ` · voie ${p.voie}` : ""}</div>}
        </div>
      ))}
    </div>
  );
}

// ── Orientation : conversation « Moov » (chat — tutoiement conservé) ─
function parseChoices(text) {
  const m = text.match(/\[CHOICES\]([\s\S]*?)\[\/CHOICES\]/);
  if (!m) return null;
  try { return JSON.parse(m[1]); } catch { return null; }
}

function Orientation({ piste, prenom, onDone }) {
  const hi = prenom ? `Salut ${prenom} !` : "Bonjour !";
  const GREET = [
    { role: "assistant", content: `${hi} Je suis Moov, ton conseiller d'orientation. Mon rôle : t'aider à y voir clair et à bâtir un projet d'études en France cohérent — le côté académique comme le côté professionnel.` },
    { role: "assistant", content: "On va discuter quelques minutes, comme un vrai entretien. Plus tu es précis, meilleures seront tes recommandations. Pour commencer : où en es-tu dans ton parcours, et qu'est-ce qui te donne envie d'étudier en France ?" },
  ];
  const [msgs, setMsgs] = useState(GREET);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [pret, setPret] = useState(false);
  const endRef = useRef(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  async function send(content) {
    if (!content.trim() || busy) return;
    const next = [...msgs, { role: "user", content }];
    setMsgs(next); setInput(""); setBusy(true);
    try {
      const r = await api.orientaChat(piste?.id, next);
      setMsgs([...next, { role: "assistant", content: r.content }]);
      if (r.pret) setPret(true);
    } catch (e) { setMsgs([...next, { role: "assistant", content: "Erreur : " + e.message }]); }
    setBusy(false);
  }

  async function generer() {
    setBusy(true);
    try {
      const rap = await api.rapport(piste.id, msgs);
      onDone(rap, await api.getPiste(piste.id));
    } catch (e) { alert(e.message); setBusy(false); }
  }

  const last = msgs[msgs.length - 1];
  const choices = last?.role === "assistant" ? parseChoices(last.content) : null;

  return (
    <div>
      <h2>Conseiller d'orientation</h2>
      <div className="card" style={{ minHeight: 260 }}>
        {msgs.map((m, i) => {
          const t = m.content.replace(/\[CHOICES\][\s\S]*?\[\/CHOICES\]/, "").replace(/\[\[PRET\]\]/g, "").trim();
          if (!t) return null;
          return <Bubble key={i} role={m.role} text={t} />;
        })}
        {busy && <div className="muted">…</div>}
        <div ref={endRef} />
      </div>

      {choices && !pret && (
        <div style={{ marginBottom: 12 }}>
          <div className="muted">{choices.question}</div>
          {choices.options.map((o) => <span key={o} className="chip chip-btn" onClick={() => send(o)}>{o}</span>)}
        </div>
      )}

      {pret ? (
        <button className="btn" disabled={busy} onClick={generer} style={{ width: "100%" }}>
          ✦ Générer mon rapport d'orientation
        </button>
      ) : (
        <div style={{ display: "flex", gap: 8 }}>
          <input className="inp" placeholder="Ta réponse…" value={input}
            onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send(input)} />
          <button className="btn" disabled={busy} onClick={() => send(input)}>Envoyer</button>
        </div>
      )}
    </div>
  );
}

function Bubble({ role, text }) {
  const me = role === "user";
  return (
    <div style={{ margin: "10px 0", textAlign: me ? "right" : "left" }}>
      <span style={{ display: "inline-block", maxWidth: "85%", padding: "10px 14px", borderRadius: 12,
        whiteSpace: "pre-wrap", textAlign: "left",
        background: me ? C.teal : C.surface2, color: me ? "#04211d" : C.ink }}>{text}</span>
    </div>
  );
}

// ── Rapport d'orientation structuré (features 1 + 2) ───────────────
function Rapport({ piste, rapport, onNext }) {
  const list = rapport?.formations || piste?.formations || [];
  const syn = rapport?.synthese || (piste?.profil || {}).synthese || null;
  const transp = rapport?.transparence || TRANSPARENCE;
  const [showT, setShowT] = useState(false);

  return (
    <div>
      <h2>Votre rapport d'orientation</h2>

      {syn && (
        <div className="card">
          {syn.synthese && <p style={{ marginTop: 0, fontSize: 15 }}>{syn.synthese}</p>}
          {syn.forces?.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontWeight: 700, color: C.teal2, marginBottom: 4 }}>Vos atouts</div>
              {syn.forces.map((f, i) => <div key={i} style={{ fontSize: 14, margin: "2px 0" }}>✓ {f}</div>)}
            </div>
          )}
          {syn.points_attention?.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontWeight: 700, color: C.gold, marginBottom: 4 }}>À travailler</div>
              {syn.points_attention.map((f, i) => <div key={i} style={{ fontSize: 14, margin: "2px 0" }}>• {f}</div>)}
            </div>
          )}
          {syn.prochaine_etape && <div className="muted" style={{ marginTop: 10 }}>→ {syn.prochaine_etape}</div>}
        </div>
      )}

      <div className="card card-soft">
        <div className="link" onClick={() => setShowT(!showT)} style={{ fontWeight: 600 }}>
          {showT ? "▾" : "▸"} {transp.titre}
        </div>
        {showT && (
          <div style={{ marginTop: 8 }}>
            <div className="muted" style={{ marginBottom: 6 }}>{transp.principe}</div>
            {transp.etapes.map((e, i) => <div key={i} style={{ fontSize: 13, margin: "4px 0" }}><b style={{ color: C.teal2 }}>{i + 1}.</b> {e}</div>)}
          </div>
        )}
      </div>

      <div className="muted" style={{ margin: "6px 0" }}>Vos 10 pistes, issues de notre base vérifiée :</div>
      {list.map((f) => (
        <div className="card" key={f.id}>
          <div style={{ fontWeight: 700 }}>{f.intitule}</div>
          <div className="muted">{[f.etablissement, f.ville, f.niveau, f.voie].filter(Boolean).join(" · ")}{f.cout_annuel ? ` · ${f.cout_annuel} €/an` : ""}</div>
          <div style={{ fontSize: 13, color: C.teal2, marginTop: 4 }}>Pourquoi : {f.explication}</div>
        </div>
      ))}
      <button className="btn" onClick={onNext} style={{ width: "100%" }}>Passer au parcours de mobilité →</button>
    </div>
  );
}

// ── Parcours : voie + RNCP + niveau (feature 7) + paiement ─────────
function Parcours({ piste, onPaid }) {
  const [voie, setVoie] = useState(piste?.voie || "");
  const [rncp, setRncp] = useState(piste?.rncp?.statut ? piste.rncp : null);
  const [intitule, setIntitule] = useState(""); const [etab, setEtab] = useState(""); const [code, setCode] = useState("");
  const [niveaux, setNiveaux] = useState([]); const [niveau, setNiveau] = useState("");
  const [pay, setPay] = useState(null); const [busy, setBusy] = useState(false); const [err, setErr] = useState("");

  useEffect(() => {
    api.getNiveaux(piste.id).then((d) => { setNiveaux(d.niveaux); setNiveau((n) => n || d.suggere || ""); }).catch(() => {});
  }, []);

  const choisir = async (v) => { setVoie(v); setErr(""); try { await api.setVoie(piste.id, v); } catch (e) { setErr(e.message); } };
  const verifier = async () => {
    setBusy(true); setErr("");
    try { setRncp(await api.verifyRncp(piste.id, intitule, etab, code)); } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const payer = async () => {
    setBusy(true); setErr("");
    try { const r = await api.pay(piste.id); setPay(r); window.open(r.payment_url, "_blank"); }
    catch (e) { setErr(e.message); } setBusy(false);
  };
  const verifierPaiement = async () => {
    setErr("");
    try {
      const s = await api.payStatus(piste.id);
      if (s.paid) { await api.genRoadmap(piste.id, niveau || null); onPaid(await api.getPiste(piste.id)); }
      else setErr("Paiement pas encore confirmé. Terminez-le puis réessayez.");
    } catch (e) { setErr(e.message); }
  };

  const deco = rncp && rncp.deconseille;
  const rncpEntete = !rncp ? null
    : deco ? { txt: "⚠ Formation déconseillée", col: C.danger, bg: "#3a1e1a" }
    : rncp.statut === "actif" ? { txt: "✓ Titre reconnu", col: C.teal2, bg: URG.fait.bg }
    : { txt: "ℹ À vérifier", col: C.gold, bg: URG.bientot.bg };

  return (
    <div>
      <h2>Parcours de mobilité</h2>
      <div className="card">
        <div className="muted">Votre voie d'accès :</div>
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <button className={voie === "public" ? "btn" : "btn-ghost"} onClick={() => choisir("public")}>Public</button>
          <button className={voie === "prive" ? "btn" : "btn-ghost"} onClick={() => choisir("prive")}>Privé</button>
        </div>
      </div>

      {voie === "prive" && (
        <div className="card">
          <div style={{ fontWeight: 700, marginBottom: 6 }}>Vérification du titre RNCP</div>
          <input className="inp" placeholder="Intitulé de la formation" value={intitule} onChange={(e) => setIntitule(e.target.value)} />
          <input className="inp" placeholder="École / établissement" value={etab} onChange={(e) => setEtab(e.target.value)} />
          <input className="inp" placeholder="Code RNCP si connu (ex. RNCP38363)" value={code} onChange={(e) => setCode(e.target.value)} />
          <button className="btn-ghost" disabled={busy} onClick={verifier}>{busy ? "Vérification…" : "Vérifier le titre"}</button>
          {rncp && rncp.statut && rncpEntete && (
            <div style={{ marginTop: 10, padding: 12, borderRadius: 10,
              background: rncpEntete.bg, color: rncpEntete.col }}>
              <div style={{ fontWeight: 700, marginBottom: 4 }}>
                {rncpEntete.txt} — {(rncp.statut || "").toUpperCase()}
              </div>
              <div style={{ color: C.ink, fontSize: 13 }}>{rncp.message}</div>
              {(rncp.intitule || rncp.code_rncp || rncp.niveau || rncp.date_echeance) && (
                <div style={{ marginTop: 8, fontSize: 13, color: C.ink }}>
                  {rncp.intitule && <div><b>Titre :</b> {rncp.intitule}</div>}
                  {rncp.code_rncp && <div><b>Numéro :</b> {rncp.code_rncp}</div>}
                  {rncp.niveau && <div><b>Niveau :</b> {rncp.niveau}</div>}
                  {rncp.date_echeance && <div><b>Fin d'enregistrement :</b> {rncp.date_echeance}</div>}
                </div>
              )}
              {rncp.source && <div className="muted" style={{ marginTop: 6 }}>{rncp.source}</div>}
            </div>
          )}
        </div>
      )}

      {voie && (
        <div className="card">
          <div style={{ fontWeight: 700, marginBottom: 6 }}>Votre niveau d'entrée</div>
          <p className="muted" style={{ marginTop: 0 }}>La feuille de route s'adapte à votre niveau (la 1re année passe par la procédure DAP).</p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {niveaux.map((n) => (
              <button key={n.id} className={niveau === n.id ? "btn btn-sm" : "btn-ghost btn-sm"} onClick={() => setNiveau(n.id)}
                title={n.sous_titre} style={{ textAlign: "left" }}>{n.label}</button>
            ))}
          </div>
          {niveau && <div className="muted" style={{ marginTop: 6 }}>{(niveaux.find((n) => n.id === niveau) || {}).sous_titre}</div>}
        </div>
      )}

      {voie && (
        <div className="card">
          <div style={{ fontWeight: 700 }}>Débloquer le parcours complet</div>
          <p className="muted">De l'admission au voyage : feuille de route avec échéances, entretien blanc Campus France, aide à la contestation et assistant.</p>
          {!pay ? (
            <button className="btn" disabled={busy} onClick={payer} style={{ width: "100%" }}>
              Payer {fcfa(pay?.amount_fcfa || PRIX_FCFA)} — mobile money
            </button>
          ) : (
            <button className="btn" onClick={verifierPaiement} style={{ width: "100%" }}>
              J'ai payé — débloquer ma feuille de route
            </button>
          )}
        </div>
      )}
      {err && <div style={{ color: C.danger, fontSize: 13 }}>{err}</div>}
    </div>
  );
}

// ── Feuille de route : arbre / liste + échéances + modale + aides ──
function buildLevels(etapes) {
  const byId = Object.fromEntries(etapes.map((e) => [e.id, e]));
  const depth = {};
  const d = (id) => {
    if (depth[id] != null) return depth[id];
    const e = byId[id];
    const deps = (e && e.depends_on) || [];
    depth[id] = deps.length ? Math.max(...deps.map(d)) + 1 : 0;
    return depth[id];
  };
  etapes.forEach((e) => d(e.id));
  const levels = [];
  etapes.forEach((e) => { (levels[depth[e.id]] ||= []).push(e); });
  return levels.filter(Boolean);
}

function Roadmap({ piste, prenom }) {
  const [rm, setRm] = useState(piste?.roadmap?.rentree ? piste.roadmap : null);
  const [mode, setMode] = useState("arbre");   // arbre | liste (feature 5)
  const [step, setStep] = useState(null);
  const [aide, setAide] = useState(null);      // "entretien" | "contestation"

  useEffect(() => { if (!rm) api.genRoadmap(piste.id).then(setRm).catch(() => {}); }, []);
  if (!rm) return <p className="muted">Chargement…</p>;

  const toggle = async (id, fait) => { const t = await api.stepDone(piste.id, id, fait); setRm(t); return t; };
  const all = rm.phases.flatMap((p) => p.etapes);
  const flat = [...all].sort((a, b) => (a.echeance || "").localeCompare(b.echeance || ""));
  const levels = buildLevels(all);
  const pa = rm.prochaine_action;

  return (
    <div>
      <h2>Ma feuille de route</h2>

      <div className="card">
        <div style={{ display: "flex", gap: 6 }}>
          <div className="stat"><b>{rm.progression_pct}%</b><span className="muted">avancement</span></div>
          <div className="stat"><b>{rm.etapes_faites}/{rm.etapes_total}</b><span className="muted">étapes</span></div>
          <div className="stat"><b style={{ color: rm.nb_en_retard ? C.danger : C.teal2 }}>{rm.nb_en_retard}</b><span className="muted">en retard</span></div>
        </div>
        <div className="progress"><i style={{ width: `${rm.progression_pct}%` }} /></div>
        <div className="muted">Rentrée visée : {rm.rentree_str}</div>
        {pa && (
          <div style={{ marginTop: 10, padding: 10, borderRadius: 10, background: URG[pa.urgence]?.bg || C.surface2 }}>
            <div className="muted">Prochaine action{pa.critique ? " · critique" : ""}</div>
            <div style={{ fontWeight: 700 }}>{pa.label}</div>
            <div style={{ color: URG[pa.urgence]?.c, fontSize: 13 }}>Échéance conseillée : {pa.echeance_str} — {decompte(pa.jours_restants)}</div>
          </div>
        )}
      </div>

      <div className="card card-soft">
        <div style={{ fontWeight: 700, marginBottom: 6 }}>Aides IA du parcours</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          <button className="btn-ghost btn-sm" onClick={() => setAide("entretien")}>🎤 Simuler l'entretien Campus France</button>
          <button className="btn-ghost btn-sm" onClick={() => setAide("contestation")}>📄 Contester un refus</button>
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "6px 0 12px", gap: 8 }}>
        <div className="seg">
          <button className={mode === "arbre" ? "on" : ""} onClick={() => setMode("arbre")}>Arbre</button>
          <button className={mode === "liste" ? "on" : ""} onClick={() => setMode("liste")}>Liste</button>
        </div>
        <div className="muted" style={{ textAlign: "right" }}>Cliquez une étape pour le détail</div>
      </div>

      {mode === "arbre"
        ? <TreeView levels={levels} onOpen={(id) => setStep(id)} />
        : <div>{flat.map((e) => <StepRow key={e.id} e={e} showPhase onOpen={() => setStep(e.id)} />)}</div>}

      <div className="muted" style={{ marginTop: 12, textAlign: "center" }}>{rm.source} · màj {rm.date_verif}</div>

      {step && <StepModal piste={piste} etape={all.find((e) => e.id === step)} onToggle={toggle}
        onClose={() => setStep(null)} onChanged={(t) => setRm(t)} />}
      {aide === "entretien" && <EntretienModal piste={piste} prenom={prenom} onClose={() => setAide(null)} />}
      {aide === "contestation" && <ContestationModal piste={piste} onClose={() => setAide(null)} />}
    </div>
  );
}

// Vraie vue arbre : niveaux de dépendance + branches parallèles + connecteurs.
function TreeView({ levels, onOpen }) {
  const icon = (s) => (s === "fait" ? "✓" : s === "ouvert" ? "◆" : "🔒");
  return (
    <div className="tree">
      {levels.map((row, i) => (
        <div key={i}>
          {i > 0 && <div className="tree-link" />}
          {row.length > 1 && <div className="tree-branch"><span>⋔ {row.length} étapes en parallèle</span></div>}
          <div className="tree-row">
            {row.map((e) => {
              const u = URG[e.urgence] || URG.avenir;
              return (
                <div key={e.id} className="tree-node" onClick={() => onOpen(e.id)}
                  style={{ borderLeftColor: u.c, opacity: e.statut === "verrouille" ? 0.62 : 1 }}>
                  <div className="lbl">
                    <span style={{ color: e.statut === "fait" ? C.ok : e.statut === "ouvert" ? C.gold : C.muted, marginRight: 6 }}>{icon(e.statut)}</span>
                    {e.label}{e.critique && <span className="badge badge-crit" style={{ marginLeft: 6 }}>Critique</span>}
                  </div>
                  <div className="muted" style={{ marginTop: 4 }}>
                    {e.echeance_str}{e.statut !== "fait" ? ` · ${decompte(e.jours_restants)}` : ""}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function StepRow({ e, showPhase, onOpen }) {
  const u = URG[e.urgence] || URG.avenir;
  const locked = e.statut === "verrouille";
  const icon = e.statut === "fait" ? "✓" : e.statut === "ouvert" ? "◆" : "🔒";
  const iconColor = e.statut === "fait" ? C.ok : e.statut === "ouvert" ? C.gold : C.muted;
  return (
    <div className="card" style={{ opacity: locked ? 0.6 : 1, marginBottom: 8, cursor: "pointer", borderLeft: `4px solid ${u.c}` }} onClick={onOpen}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div style={{ fontWeight: 600 }}>
          <span style={{ color: iconColor, marginRight: 6 }}>{icon}</span>{e.label}
          {e.critique && <span className="badge badge-crit" style={{ marginLeft: 8 }}>Critique</span>}
        </div>
        {e.statut !== "fait" && <span style={{ color: u.c, fontSize: 12, fontWeight: 700, whiteSpace: "nowrap" }}>{u.label}</span>}
      </div>
      <div className="muted" style={{ marginTop: 4 }}>
        {showPhase ? `${e.phase} · ` : ""}Échéance : {e.echeance_str}{e.statut !== "fait" ? ` · ${decompte(e.jours_restants)}` : ""}
      </div>
    </div>
  );
}

function StepModal({ piste, etape, onToggle, onClose, onChanged }) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!etape) return null;
  const u = URG[etape.urgence] || URG.avenir;
  const done = etape.statut === "fait";
  const locked = etape.statut === "verrouille";

  const marquer = async (fait) => {
    setBusy(true);
    try { const t = await onToggle(etape.id, fait); onChanged(t); setConfirm(false); onClose(); }
    catch (e) { alert(e.message); }
    setBusy(false);
  };
  const onMarkClick = () => { if (etape.critique && !done) setConfirm(true); else marquer(!done); };

  return (
    <div className="modal-ov" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div style={{ fontWeight: 700, fontSize: 17 }}>{etape.label}
            {etape.critique && <span className="badge badge-crit" style={{ marginLeft: 8 }}>Critique</span>}</div>
          <button className="btn-ghost btn-sm" onClick={onClose}>Fermer</button>
        </div>

        <div style={{ display: "inline-block", padding: "4px 10px", borderRadius: 8, background: u.bg, color: u.c, fontSize: 13, fontWeight: 700 }}>
          {u.label} · {etape.echeance_str}{!done ? ` · ${decompte(etape.jours_restants)}` : ""}
        </div>

        <p style={{ marginTop: 12 }}>{etape.conseil}</p>
        {etape.docs?.length > 0 && (
          <div style={{ marginBottom: 8 }}>
            <div className="muted">Documents</div>
            {etape.docs.map((doc) => <span key={doc} className="chip">{doc}</span>)}
          </div>
        )}
        {locked && <div className="muted">Cette étape s'ouvrira une fois les précédentes bouclées.</div>}

        {!locked && !confirm && (
          <div style={{ marginTop: 8 }}>
            <button className={done ? "btn-ghost" : "btn"} disabled={busy} onClick={onMarkClick}>
              {done ? "Annuler « fait »" : "Marquer comme fait"}
            </button>
          </div>
        )}

        {confirm && (
          <div style={{ marginTop: 10, padding: 12, borderRadius: 10, background: "#3a1e1a" }}>
            <div style={{ color: C.danger, fontWeight: 700, marginBottom: 6 }}>Étape critique</div>
            <div className="muted" style={{ marginBottom: 10 }}>Confirmez que cette étape est bien bouclée : la manquer peut faire perdre l'année. Êtes-vous sûr(e) ?</div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn" disabled={busy} onClick={() => marquer(true)}>Oui, c'est fait</button>
              <button className="btn-ghost" onClick={() => setConfirm(false)}>Pas encore</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Simulation d'entretien Campus France (feature 10) — chat ───────
function EntretienModal({ piste, prenom, onClose }) {
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState(""); const [busy, setBusy] = useState(false); const [fin, setFin] = useState(false);
  const endRef = useRef(null);
  useEffect(() => { start(); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  async function start() {
    setBusy(true);
    try { const r = await api.entretien(piste.id, []); setMsgs([{ role: "assistant", content: r.content }]); setFin(!!r.fin); }
    catch (e) { setMsgs([{ role: "assistant", content: "Erreur : " + e.message }]); }
    setBusy(false);
  }
  async function send() {
    if (!input.trim() || busy) return;
    const next = [...msgs, { role: "user", content: input }];
    setMsgs(next); setInput(""); setBusy(true);
    try { const r = await api.entretien(piste.id, next); setMsgs([...next, { role: "assistant", content: r.content }]); setFin(!!r.fin); }
    catch (e) { setMsgs([...next, { role: "assistant", content: "Erreur : " + e.message }]); }
    setBusy(false);
  }
  const clean = (t) => t.replace(/\[\[FIN\]\]/g, "").trim();

  return (
    <div className="modal-ov" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div style={{ fontWeight: 700, fontSize: 17 }}>🎤 Entretien Campus France (blanc)</div>
          <button className="btn-ghost btn-sm" onClick={onClose}>Fermer</button>
        </div>
        <div className="muted" style={{ marginBottom: 6 }}>Entraînez-vous comme le vrai entretien. Aucune donnée officielle inventée.</div>
        <div style={{ minHeight: 160 }}>
          {msgs.map((m, i) => <Bubble key={i} role={m.role} text={clean(m.content)} />)}
          {busy && <div className="muted">…</div>}
          <div ref={endRef} />
        </div>
        {fin ? (
          <button className="btn" onClick={() => { setMsgs([]); setFin(false); start(); }} style={{ width: "100%" }}>Refaire un entretien</button>
        ) : (
          <div style={{ display: "flex", gap: 8 }}>
            <input className="inp" placeholder="Votre réponse…" value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} />
            <button className="btn" disabled={busy} onClick={send}>Répondre</button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Aide à la contestation d'un refus (feature 11) ─────────────────
function ContestationModal({ piste, onClose }) {
  const [type, setType] = useState("admission");
  const [formation, setFormation] = useState(""); const [etab, setEtab] = useState("");
  const [motif, setMotif] = useState(""); const [args, setArgs] = useState("");
  const [res, setRes] = useState(null); const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const [copied, setCopied] = useState(false);

  async function generer() {
    setBusy(true); setErr("");
    try { setRes(await api.contestation(piste.id, { type_refus: type, formation, etablissement: etab, motif, arguments: args })); }
    catch (e) { setErr(e.message); }
    setBusy(false);
  }
  const copier = async () => { try { await navigator.clipboard.writeText(res.lettre); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch {} };

  return (
    <div className="modal-ov" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div style={{ fontWeight: 700, fontSize: 17 }}>📄 Contester un refus</div>
          <button className="btn-ghost btn-sm" onClick={onClose}>Fermer</button>
        </div>

        {!res && (
          <>
            <div className="muted">Type de refus</div>
            <div className="seg" style={{ marginBottom: 8 }}>
              <button className={type === "admission" ? "on" : ""} onClick={() => setType("admission")}>Admission</button>
              <button className={type === "visa" ? "on" : ""} onClick={() => setType("visa")}>Visa</button>
            </div>
            <input className="inp" placeholder="Formation concernée" value={formation} onChange={(e) => setFormation(e.target.value)} />
            <input className="inp" placeholder="Établissement / consulat" value={etab} onChange={(e) => setEtab(e.target.value)} />
            <input className="inp" placeholder="Motif du refus (si connu)" value={motif} onChange={(e) => setMotif(e.target.value)} />
            <textarea className="ta" placeholder="Les éléments que vous voulez faire valoir (nouveaux résultats, motivation, corrections…)" value={args} onChange={(e) => setArgs(e.target.value)} />
            {err && <div style={{ color: C.danger, fontSize: 13 }}>{err}</div>}
            <button className="btn" disabled={busy} onClick={generer} style={{ width: "100%", marginTop: 6 }}>Générer mon aide au recours</button>
          </>
        )}

        {res && (
          <>
            <div style={{ fontWeight: 700, color: C.teal2, marginBottom: 4 }}>Voies possibles</div>
            {res.voies.map((v, i) => <div key={i} style={{ fontSize: 14, margin: "3px 0" }}>• {v}</div>)}
            <div style={{ fontWeight: 700, color: C.gold, margin: "10px 0 4px" }}>Conseils</div>
            {res.conseils.map((v, i) => <div key={i} style={{ fontSize: 14, margin: "3px 0" }}>→ {v}</div>)}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "12px 0 4px" }}>
              <div style={{ fontWeight: 700 }}>Brouillon de courrier</div>
              <button className="btn-ghost btn-sm" onClick={copier}>{copied ? "Copié ✓" : "Copier"}</button>
            </div>
            <textarea className="ta" style={{ minHeight: 220 }} value={res.lettre} onChange={(e) => setRes({ ...res, lettre: e.target.value })} />
            {res.avertissement && <div className="muted" style={{ marginTop: 6 }}>⚠︎ {res.avertissement}</div>}
            <button className="btn-ghost" onClick={() => setRes(null)} style={{ marginTop: 10 }}>← Modifier ma situation</button>
          </>
        )}
      </div>
    </div>
  );
}
