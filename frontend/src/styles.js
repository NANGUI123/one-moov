// styles.js — Palette et CSS globaux.
//
// Les couleurs sont exposées comme des variables CSS (:root) et l'objet
// `C` renvoie les `var(--...)` correspondantes. Résultat : basculer light
// ↔ dark ne demande qu'un `data-theme` sur <html>. Les styles inline React
// (style={{background: C.teal}}) suivent automatiquement, sans re-rendu.
//
// Deux palettes :
//   light  →  blanc + vert (thème par défaut, aligné sur le manifest PWA
//             et sur le kit de marque).
//   dark   →  vert profond, contraste renforcé — historique de l'app.

export const C = {
  bg: "var(--bg)",
  surface: "var(--surface)",
  surface2: "var(--surface-2)",
  line: "var(--line)",
  ink: "var(--ink)",
  fg: "var(--fg)",
  muted: "var(--muted)",
  teal: "var(--teal)",
  teal2: "var(--teal-2)",
  gold: "var(--gold)",
  danger: "var(--danger)",
  ok: "var(--ok)",
};

// Couleurs d'urgence du moteur d'échéances. Chaque tuple porte sa couleur
// texte (c) et son fond doux (bg) — les deux viennent des variables et
// respectent la palette du thème actif.
export const URG = {
  fait: { c: "var(--ok)", label: "Fait", bg: "var(--ok-soft)" },
  retard: { c: "var(--danger)", label: "En retard", bg: "var(--danger-soft)" },
  bientot: { c: "var(--gold)", label: "Bientôt", bg: "var(--gold-soft)" },
  avenir: { c: "var(--muted)", label: "À venir", bg: "var(--surface-2)" },
};

// Nom de la clé localStorage pour le thème choisi par l'étudiant. Une
// absence de valeur = suivre la préférence système (prefers-color-scheme).
export const CLE_THEME = "onemoov_theme";

// Palettes déclarées côté CSS pour permettre à `prefers-color-scheme` et à
// l'attribut `data-theme` sur <html> de basculer sans JS.
const PALETTE_LIGHT = `
  --bg: #ffffff;
  --surface: #ffffff;
  --surface-2: #f0f6f4;
  --line: #d9e6e2;
  --ink: #0a2620;
  --fg: #1e3a34;
  --muted: #5d726c;
  --teal: #0e6b5c;
  --teal-2: #0a5045;
  --teal-soft: #d5e7e2;
  --btn-ink: #ffffff;
  --gold: #b8862c;
  --gold-soft: #fff5d6;
  --danger: #b8442c;
  --danger-soft: #fde3dc;
  --ok: #0e6b5c;
  --ok-soft: #d5e7e2;
  --scrim: rgba(10, 38, 32, 0.35);
  --shadow-card: 0 1px 2px rgba(10, 38, 32, .04), 0 4px 12px rgba(10, 38, 32, .04);
`;
const PALETTE_DARK = `
  --bg: #0c1514;
  --surface: #15211f;
  --surface-2: #1a2724;
  --line: #28352f;
  --ink: #eef4f1;
  --fg: #d5e2dd;
  --muted: #93a29d;
  --teal: #5bb9ac;
  --teal-2: #7fcdc0;
  --teal-soft: #163632;
  --btn-ink: #04211d;
  --gold: #e6ac53;
  --gold-soft: #33290f;
  --danger: #e2725b;
  --danger-soft: #3a1e1a;
  --ok: #5bb9ac;
  --ok-soft: #12332d;
  --scrim: rgba(0, 0, 0, .55);
  --shadow-card: none;
`;

export const GLOBAL_CSS = `
  :root { color-scheme: light; ${PALETTE_LIGHT} }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) { color-scheme: dark; ${PALETTE_DARK} }
  }
  :root[data-theme="dark"] { color-scheme: dark; ${PALETTE_DARK} }
  :root[data-theme="light"] { color-scheme: light; ${PALETTE_LIGHT} }

  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--fg);
    font-family: 'Inter', system-ui, -apple-system, sans-serif; line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    transition: background-color .2s ease, color .2s ease; }
  h1,h2,h3 { font-family: 'Poppins', system-ui, sans-serif; color: var(--ink); }
  h2 { font-size: 22px; margin: 6px 0 12px; }
  button { font-family: inherit; cursor: pointer; }
  input, button, textarea, select { font-size: 15px; font-family: inherit; }
  .wrap { max-width: 760px; margin: 0 auto; padding: 20px 16px 72px; }

  .card { background: var(--surface); border: 1px solid var(--line);
    border-radius: 14px; padding: 16px; margin-bottom: 12px;
    box-shadow: var(--shadow-card); }
  .card-soft { background: var(--surface-2); box-shadow: none; }

  .btn { background: var(--teal); color: var(--btn-ink); border: 0;
    border-radius: 10px; padding: 12px 18px; font-weight: 700;
    transition: filter .15s, transform .15s; }
  .btn:hover:not(:disabled) { filter: brightness(1.06); }
  .btn:disabled { opacity: .5; cursor: default; }
  .btn-ghost { background: transparent; color: var(--teal);
    border: 1px solid var(--line); border-radius: 10px; padding: 10px 16px;
    font-weight: 600; transition: border-color .15s, color .15s; }
  .btn-ghost:hover { border-color: var(--teal); color: var(--teal-2); }
  .btn-danger { background: transparent; color: var(--danger);
    border: 1px solid var(--danger); border-radius: 10px; padding: 10px 16px;
    font-weight: 600; }
  .btn-sm { padding: 7px 12px; font-size: 13px; border-radius: 8px; }

  .inp, .ta { width: 100%; padding: 12px; border-radius: 10px;
    border: 1px solid var(--line); background: var(--surface-2); color: var(--fg);
    margin: 6px 0; transition: border-color .15s; }
  .inp:focus, .ta:focus { outline: none; border-color: var(--teal); }
  .ta { resize: vertical; min-height: 120px; line-height: 1.55; }

  .chip { display: inline-block; background: var(--surface-2);
    border: 1px solid var(--line); color: var(--teal);
    border-radius: 20px; padding: 6px 12px; margin: 4px 6px 4px 0; font-size: 13px; }
  .chip-btn { cursor: pointer; transition: border-color .15s, background-color .15s; }
  .chip-btn:hover { border-color: var(--teal); background: var(--teal-soft); }

  .muted { color: var(--muted); font-size: 13px; }

  .badge { display: inline-block; font-size: 11px; font-weight: 700;
    letter-spacing: .3px; border-radius: 6px; padding: 2px 8px; text-transform: uppercase; }
  .badge-crit { background: var(--danger-soft); color: var(--danger);
    border: 1px solid var(--danger); }

  .progress { height: 10px; background: var(--surface-2); border-radius: 20px;
    overflow: hidden; margin: 8px 0; }
  .progress > i { display: block; height: 100%;
    background: linear-gradient(90deg, var(--teal), var(--teal-2));
    border-radius: 20px; transition: width .4s; }

  .seg { display: inline-flex; background: var(--surface-2);
    border: 1px solid var(--line); border-radius: 10px; padding: 3px; gap: 3px; }
  .seg button { background: transparent; border: 0; color: var(--muted);
    border-radius: 8px; padding: 7px 14px; font-weight: 600; }
  .seg button.on { background: var(--teal); color: var(--btn-ink); }

  .stat { flex: 1; text-align: center; padding: 6px; }
  .stat b { display: block; font-family: 'Poppins'; font-size: 22px; color: var(--teal); }

  .modal-ov { position: fixed; inset: 0; background: var(--scrim);
    display: flex; align-items: flex-end; justify-content: center; z-index: 50; }
  .modal { background: var(--surface); width: 100%; max-width: 760px;
    max-height: 88vh; overflow: auto; border: 1px solid var(--line);
    border-radius: 16px 16px 0 0; padding: 18px; box-shadow: var(--shadow-card); }
  .modal-head { display: flex; justify-content: space-between; align-items: center;
    gap: 10px; margin-bottom: 8px; }

  .link { color: var(--teal); cursor: pointer; text-decoration: underline;
    text-underline-offset: 3px; }
  .link:hover { color: var(--teal-2); }

  .tree { display: flex; flex-direction: column; }
  .tree-link { height: 22px; position: relative; }
  .tree-link::before { content: ''; position: absolute; left: 50%; top: 0; bottom: 0;
    width: 2px; margin-left: -1px; background: var(--line); }
  .tree-branch { text-align: center; margin: 2px 0 -2px; }
  .tree-branch span { font-size: 11px; color: var(--muted); background: var(--surface-2);
    border: 1px solid var(--line); border-radius: 20px; padding: 2px 10px; }
  .tree-row { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; }
  .tree-node { flex: 1 1 200px; max-width: 460px; background: var(--surface);
    border: 1px solid var(--line); border-left-width: 4px; border-radius: 12px;
    padding: 10px 12px; cursor: pointer; transition: border-color .15s, box-shadow .15s; }
  .tree-node:hover { border-color: var(--teal); box-shadow: var(--shadow-card); }
  .tree-node .lbl { font-weight: 600; font-size: 14px; }

  /* ── Écran d'accueil : dégradé fixe, hors des tokens du thème ───── */
  .accueil {
    min-height: 100vh;
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
    padding: 24px 24px 32px;
    color: #ffffff;
    background: linear-gradient(180deg,
      #0e6b5c 0%,
      #1a6a70 42%,
      #2c5a9e 78%,
      #3f5cb8 100%);
    box-sizing: border-box;
    overflow: hidden;
    position: relative;
  }
  .accueil::before {
    content: "";
    position: absolute;
    inset: -20% -20% auto -20%;
    height: 55%;
    background: radial-gradient(60% 80% at 50% 0%, rgba(255,255,255,.12), rgba(255,255,255,0) 70%);
    pointer-events: none;
  }
  .accueil-marque {
    display: flex; align-items: center; gap: 10px;
    z-index: 1;
    max-width: 480px;
    width: 100%;
    margin: 0 auto;
  }
  .accueil-logo {
    width: 34px; height: 34px;
    background: rgba(255,255,255,.18);
    border: 1px solid rgba(255,255,255,.28);
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    color: #ffffff;
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
  }
  .accueil-marque-nom {
    font-family: 'Poppins', sans-serif;
    font-weight: 700; font-size: 20px;
    letter-spacing: -0.01em;
    color: #ffffff;
  }
  /* Contenu centré à largeur mobile-native, même sur desktop.
     C'est la composition la plus fidèle à la maquette : les grands
     écrans montrent la landing dans une colonne étroite plutôt qu'un
     texte collé à gauche et des boutons flottant au milieu. */
  .accueil-contenu {
    flex: 1;
    display: flex;
    flex-direction: column;
    width: 100%;
    max-width: 480px;
    margin: 0 auto;
    z-index: 1;
  }
  .accueil-corps {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding-top: 40px;
  }
  .accueil-eyebrow {
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: rgba(255,255,255,.72);
    margin-bottom: 14px;
  }
  .accueil-titre {
    font-family: 'Poppins', sans-serif;
    font-weight: 700;
    font-size: clamp(28px, 6vw, 40px);
    line-height: 1.08;
    color: #ffffff;
    letter-spacing: -0.02em;
    text-wrap: balance;
    margin: 0 0 12px;
  }
  .accueil-sous {
    font-size: 16px;
    line-height: 1.5;
    color: rgba(255,255,255,.86);
    margin: 0;
    max-width: 30ch;
  }
  .accueil-actions {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding-bottom: max(4px, env(safe-area-inset-bottom, 0px));
  }
  .accueil-btn {
    border: 0;
    border-radius: 14px;
    padding: 16px 22px;
    font-family: 'Inter', sans-serif;
    font-size: 16px;
    font-weight: 700;
    cursor: pointer;
    transition: transform .12s ease, filter .15s ease, background-color .15s ease;
  }
  .accueil-btn:active { transform: scale(.985); }
  .accueil-btn.primaire {
    background: #ffffff;
    color: #0e6b5c;
    box-shadow: 0 8px 24px rgba(10, 40, 30, .18);
  }
  .accueil-btn.primaire:hover { filter: brightness(1.02); }
  .accueil-btn.secondaire {
    background: rgba(255,255,255,.16);
    color: #ffffff;
    border: 1px solid rgba(255,255,255,.22);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
  }
  .accueil-btn.secondaire:hover { background: rgba(255,255,255,.22); }
  .accueil-legende {
    text-align: center;
    font-size: 12.5px;
    color: rgba(255,255,255,.72);
    margin-top: 8px;
  }
  @media (min-width: 720px) {
    .accueil-corps { padding-top: 80px; }
  }

  /* Bouton de bascule du thème (soleil / lune). */
  .theme-toggle {
    background: transparent; border: 1px solid var(--line);
    color: var(--muted); border-radius: 999px;
    width: 34px; height: 34px; display: inline-flex;
    align-items: center; justify-content: center;
    padding: 0; transition: color .15s, border-color .15s, transform .15s;
  }
  .theme-toggle:hover { color: var(--teal); border-color: var(--teal); }
  .theme-toggle:active { transform: scale(0.94); }
  .theme-toggle svg { width: 16px; height: 16px; }

  @media (min-width: 620px) {
    .modal-ov { align-items: center; }
    .modal { border-radius: 16px; }
  }
  @media (max-width: 500px) {
    .wrap { padding: 16px 14px 72px; }
  }
  @media (prefers-reduced-motion: reduce) {
    * { transition: none !important; }
  }
`;
