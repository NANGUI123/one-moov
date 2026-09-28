// api.js — couche fetch + jeton JWT (localStorage)
const TOKEN_KEY = "onemoov_token";
export const getToken = () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } };
export const setToken = (t) => { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch {} };

async function req(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  const tok = getToken();
  if (tok) headers.Authorization = "Bearer " + tok;
  const res = await fetch("/api" + path, {
    method, headers, body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Erreur ${res.status}`);
  return data;
}

export const api = {
  register: (email, password, prenom) => req("POST", "/auth/register", { email, password, prenom }),
  login: (email, password) => req("POST", "/auth/login", { email, password }),
  resendVerif: (email) => req("POST", "/auth/resend", { email }),
  forgot: (email) => req("POST", "/auth/forgot", { email }),
  me: () => req("GET", "/auth/me"),

  // Pistes / tableau de bord (feature 14)
  listPistes: () => req("GET", "/pistes"),
  createPiste: (pays = "Cameroun") => req("POST", "/pistes", { pays }),
  getPiste: (id) => req("GET", `/pistes/${id}`),

  // Orientation (features 1, 2)
  orientaChat: (piste_id, messages) => req("POST", "/orientation/chat", { piste_id, messages }),
  formations: (piste_id, messages, profil = null) => req("POST", "/orientation/formations", { piste_id, messages, profil }),
  rapport: (piste_id, messages, profil = null) => req("POST", "/orientation/rapport", { piste_id, messages, profil }),

  // Parcours / RNCP / niveau (feature 7)
  setVoie: (piste_id, voie) => req("POST", "/roadmap/voie", { piste_id, voie }),
  getNiveaux: (piste_id) => req("GET", `/roadmap/niveaux?piste_id=${piste_id}`),
  verifyRncp: (piste_id, intitule, etablissement, code_rncp = "") =>
    req("POST", "/rncp/verify", { piste_id, intitule, etablissement, code_rncp }),

  // Paiement
  pay: (piste_id) => req("POST", "/paiement/create", { piste_id }),
  payStatus: (piste_id) => req("GET", `/paiement/status?piste_id=${piste_id}`),

  // Roadmap (features 3, 5, 6)
  genRoadmap: (piste_id, niveau = null, rentree = null) => req("POST", "/roadmap/generate", { piste_id, niveau, rentree }),
  stepDone: (piste_id, step_id, fait) => req("POST", "/roadmap/step", { piste_id, step_id, fait }),
  chatbot: (piste_id, etape, messages) => req("POST", "/chatbot", { piste_id, etape, messages }),

  // Aides IA (features 10, 11)
  entretien: (piste_id, messages) => req("POST", "/aides/entretien", { piste_id, messages }),
  contestation: (piste_id, payload) => req("POST", "/aides/contestation", { piste_id, ...payload }),

  myCosts: () => req("GET", "/me/costs"),
};
