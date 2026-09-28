export const C = {
  bg: "#0c1514", surface: "#15211f", surface2: "#1a2724", line: "#28352f",
  ink: "#e9f1ee", muted: "#93a29d", teal: "#5bb9ac", teal2: "#7fcdc0",
  gold: "#e6ac53", danger: "#e2725b", ok: "#5bb9ac",
};

// Couleurs d'urgence du moteur d'échéances (feature 3)
export const URG = {
  fait: { c: C.ok, label: "Fait", bg: "#12332d" },
  retard: { c: C.danger, label: "En retard", bg: "#3a1e1a" },
  bientot: { c: C.gold, label: "Bientôt", bg: "#33290f" },
  avenir: { c: C.muted, label: "À venir", bg: C.surface2 },
};

export const GLOBAL_CSS = `
  * { box-sizing: border-box; }
  body { margin: 0; background: ${C.bg}; color: ${C.ink};
    font-family: 'Inter', system-ui, -apple-system, sans-serif; line-height: 1.5; }
  h1,h2,h3 { font-family: 'Poppins', system-ui, sans-serif; }
  h2 { font-size: 22px; margin: 6px 0 12px; }
  button { font-family: inherit; cursor: pointer; }
  input, button, textarea, select { font-size: 15px; font-family: inherit; }
  .wrap { max-width: 760px; margin: 0 auto; padding: 20px 16px 72px; }
  .card { background: ${C.surface}; border: 1px solid ${C.line}; border-radius: 14px; padding: 16px; margin-bottom: 12px; }
  .card-soft { background: ${C.surface2}; }
  .btn { background: ${C.teal}; color: #04211d; border: 0; border-radius: 10px; padding: 12px 18px; font-weight: 700; transition: filter .15s; }
  .btn:hover:not(:disabled) { filter: brightness(1.06); }
  .btn:disabled { opacity: .5; cursor: default; }
  .btn-ghost { background: transparent; color: ${C.teal2}; border: 1px solid ${C.line}; border-radius: 10px; padding: 10px 16px; font-weight: 600; }
  .btn-ghost:hover { border-color: ${C.teal}; }
  .btn-danger { background: transparent; color: ${C.danger}; border: 1px solid #4a2620; border-radius: 10px; padding: 10px 16px; font-weight: 600; }
  .btn-sm { padding: 7px 12px; font-size: 13px; border-radius: 8px; }
  .inp, .ta { width: 100%; padding: 12px; border-radius: 10px; border: 1px solid ${C.line};
    background: ${C.surface2}; color: ${C.ink}; margin: 6px 0; }
  .ta { resize: vertical; min-height: 120px; line-height: 1.55; }
  .chip { display:inline-block; background:${C.surface2}; border:1px solid ${C.line}; color:${C.teal2};
    border-radius: 20px; padding: 6px 12px; margin: 4px 6px 4px 0; font-size: 13px; }
  .chip-btn { cursor: pointer; transition: border-color .15s; }
  .chip-btn:hover { border-color: ${C.teal}; }
  .muted { color: ${C.muted}; font-size: 13px; }
  .badge { display:inline-block; font-size: 11px; font-weight: 700; letter-spacing: .3px;
    border-radius: 6px; padding: 2px 8px; text-transform: uppercase; }
  .badge-crit { background: #3a1e1a; color: ${C.danger}; border: 1px solid #542a23; }
  .progress { height: 10px; background: ${C.surface2}; border-radius: 20px; overflow: hidden; margin: 8px 0; }
  .progress > i { display:block; height: 100%; background: linear-gradient(90deg, ${C.teal}, ${C.teal2}); border-radius: 20px; transition: width .4s; }
  .seg { display:inline-flex; background: ${C.surface2}; border: 1px solid ${C.line}; border-radius: 10px; padding: 3px; gap: 3px; }
  .seg button { background: transparent; border: 0; color: ${C.muted}; border-radius: 8px; padding: 7px 14px; font-weight: 600; }
  .seg button.on { background: ${C.teal}; color: #04211d; }
  .stat { flex:1; text-align:center; padding: 6px; }
  .stat b { display:block; font-family:'Poppins'; font-size: 22px; color: ${C.teal2}; }
  .modal-ov { position: fixed; inset: 0; background: rgba(0,0,0,.55); display:flex; align-items:flex-end; justify-content:center; z-index: 50; }
  .modal { background: ${C.surface}; width: 100%; max-width: 760px; max-height: 88vh; overflow:auto;
    border: 1px solid ${C.line}; border-radius: 16px 16px 0 0; padding: 18px; }
  .modal-head { display:flex; justify-content:space-between; align-items:center; gap: 10px; margin-bottom: 8px; }
  .link { color: ${C.teal2}; cursor: pointer; text-decoration: underline; text-underline-offset: 3px; }
  .tree { display:flex; flex-direction:column; }
  .tree-link { height: 22px; position: relative; }
  .tree-link::before { content:''; position:absolute; left:50%; top:0; bottom:0; width:2px; margin-left:-1px; background:${C.line}; }
  .tree-branch { text-align:center; margin: 2px 0 -2px; }
  .tree-branch span { font-size:11px; color:${C.muted}; background:${C.surface2}; border:1px solid ${C.line}; border-radius:20px; padding:2px 10px; }
  .tree-row { display:flex; gap:10px; justify-content:center; flex-wrap:wrap; }
  .tree-node { flex:1 1 200px; max-width:460px; background:${C.surface}; border:1px solid ${C.line};
    border-left-width:4px; border-radius:12px; padding:10px 12px; cursor:pointer; transition:border-color .15s; }
  .tree-node:hover { border-color:${C.teal}; }
  .tree-node .lbl { font-weight:600; font-size:14px; }
  @media (min-width: 620px){ .modal-ov { align-items:center; } .modal { border-radius: 16px; } }
  @media (max-width: 500px) { .wrap { padding: 16px 14px 72px; } }
`;
