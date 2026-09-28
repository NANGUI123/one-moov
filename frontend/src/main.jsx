import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { GLOBAL_CSS } from "./styles.js";

const style = document.createElement("style");
style.textContent = GLOBAL_CSS;
document.head.appendChild(style);

const fonts = document.createElement("link");
fonts.rel = "stylesheet";
fonts.href = "https://fonts.googleapis.com/css2?family=Poppins:wght@600;700&family=Inter:wght@400;500;600;700&display=swap";
document.head.appendChild(fonts);

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode><App /></React.StrictMode>
);
