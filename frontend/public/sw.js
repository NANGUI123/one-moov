/**
 * Service worker de One Moov.
 *
 * Il ne met en cache que la coquille de l'application : le HTML, le JS, le
 * CSS, les icônes. C'est ce qui permet à l'étudiant d'installer One Moov sur
 * son téléphone et de l'ouvrir même avec une connexion instable.
 *
 * Il ne met JAMAIS en cache /api/. C'est délibéré et c'est la contrainte
 * centrale du produit : les échanges avec les agents contiennent le projet de
 * l'étudiant, et rien de tout cela ne doit survivre sur l'appareil. Le cache
 * du navigateur, lui, survit à la fermeture de l'application — au contraire
 * du sessionStorage où vit l'état. Mettre une réponse d'agent en cache
 * annulerait la promesse de non-conservation.
 *
 * Stratégie : réseau d'abord pour la navigation (l'étudiant voit toujours la
 * dernière version), cache d'abord pour les fichiers versionnés par Vite
 * (leur nom change à chaque build, ils ne peuvent pas être périmés).
 *
 * Le délai de garde sur la navigation
 * ----------------------------------
 * « Réseau d'abord » suppose que le réseau répond ou échoue. Sur une connexion
 * mobile saturée, il fait ni l'un ni l'autre : la requête reste en attente, et
 * l'application ne s'ouvre pas du tout. C'est le pire des cas, pire qu'être
 * franchement hors ligne. Au-delà de DELAI_RESEAU, on sert donc la coquille
 * mise en cache. L'étudiant ouvre son application, et la version en cache
 * n'est jamais périmée de plus d'un déploiement.
 */

// À incrémenter à chaque publication qui touche la coquille (index.html,
// styles, palette). L'activation du nouveau SW efface les caches
// nommés autrement — les étudiants voient la nouvelle version dès leur
// prochaine ouverture, sans manipulation à faire.
const VERSION = "one-moov-v9";

// Mesuré sur une 3G encombrée : au-delà de deux secondes et demie, l'étudiant
// a déjà l'impression que l'application est cassée.
const DELAI_RESEAU = 2500;
const COQUILLE = ["/", "/index.html", "/manifest.webmanifest", "/icons/icone.svg"];

self.addEventListener("install", (evt) => {
  evt.waitUntil(
    caches
      .open(VERSION)
      // addAll échoue en bloc si un seul fichier manque : on tolère les absents.
      .then((cache) => Promise.allSettled(COQUILLE.map((u) => cache.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (evt) => {
  evt.waitUntil(
    caches
      .keys()
      .then((cles) => Promise.all(cles.filter((c) => c !== VERSION).map((c) => caches.delete(c))))
      .then(() => self.clients.claim())
  );
});

/**
 * Sert la navigation : le réseau s'il répond vite, la coquille sinon.
 *
 * La réponse réseau est mise en cache même quand le délai a déjà expiré et que
 * la coquille a été servie : la prochaine ouverture profite de la version
 * fraîche.
 */
async function navigation(req) {
  const cache = await caches.open(VERSION);

  const reseau = fetch(req)
    .then((reponse) => {
      if (reponse.ok) cache.put("/index.html", reponse.clone());
      return reponse;
    })
    .catch(() => null);

  const attente = new Promise((resoudre) => setTimeout(() => resoudre(null), DELAI_RESEAU));
  const rapide = await Promise.race([reseau, attente]);
  if (rapide) return rapide;

  const enCache = await cache.match("/index.html");
  if (enCache) return enCache;

  // Rien en cache : il reste à espérer que le réseau finisse par répondre.
  return (await reseau) || Response.error();
}

self.addEventListener("fetch", (evt) => {
  const req = evt.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Tout ce qui touche aux agents sort du service worker sans être intercepté.
  if (url.pathname.startsWith("/api/") || url.origin !== self.location.origin) return;

  // Navigation : réseau d'abord, coquille en secours si hors ligne OU si le
  // réseau traîne trop.
  if (req.mode === "navigate") {
    evt.respondWith(navigation(req));
    return;
  }

  // Ressources statiques : cache d'abord, puis réseau qu'on archive.
  evt.respondWith(
    caches.match(req).then(
      (enCache) =>
        enCache ||
        fetch(req).then((reponse) => {
          if (reponse.ok && reponse.type === "basic") {
            const copie = reponse.clone();
            caches.open(VERSION).then((cache) => cache.put(req, copie));
          }
          return reponse;
        })
    )
  );
});
