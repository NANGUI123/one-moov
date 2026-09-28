import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { GLOBAL_CSS, CLE_THEME } from "./styles.js";

// Injecte les CSS globaux (palette + composants) avant le premier rendu.
const style = document.createElement("style");
style.textContent = GLOBAL_CSS;
document.head.appendChild(style);

// Fixe le thème choisi par l'étudiant avant le premier rendu — évite le
// flash blanc au chargement quand la préférence est « dark ». Une absence
// de valeur laisse `prefers-color-scheme` décider.
try {
  const t = localStorage.getItem(CLE_THEME);
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
} catch { /* localStorage indisponible : on garde le mode auto. */ }

const fonts = document.createElement("link");
fonts.rel = "stylesheet";
fonts.href = "https://fonts.googleapis.com/css2?family=Poppins:wght@600;700&family=Inter:wght@400;500;600;700&display=swap";
document.head.appendChild(fonts);

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode><App /></React.StrictMode>
);
