# Déploiement One Moov — Render + Cloudflare Pages

Le back tourne sur **Render.com** (Python 3.11, Postgres 16 managée). Le
front tourne sur **Cloudflare Pages** (CDN mondial, gratuit,
PWA-friendly). Cette séparation coûte 0 € pour la démonstration et scale
sans changement d'architecture.

```
┌────────────────────┐     https      ┌─────────────────────────┐
│  Cloudflare Pages  │───────────────▶│  Render — one-moov-api  │
│  (front React PWA) │  /api/* proxy  │  (FastAPI + Postgres)   │
└────────────────────┘                └─────────────────────────┘
        ▲
        │ install PWA sur mobile
   Étudiant
```

Total : environ 20 minutes pour tout mettre en ligne la première fois.

---

## 1. Backend — Render (5 minutes actives, ~5 minutes de build)

Le fichier `render.yaml` à la racine décrit toute l'infrastructure. Render
lit ce fichier et provisionne le service web + la base Postgres d'un
coup.

**Étapes :**

1. **Compte Render.** [dashboard.render.com](https://dashboard.render.com/register) →
   se connecter avec GitHub.
2. **Nouveau Blueprint.** Dans le dashboard : « **New +** » → « **Blueprint** » →
   sélectionner le dépôt `NANGUI123/one-moov` → brancher sur la branche à
   déployer (par défaut `main`).
3. Render détecte `render.yaml` et affiche le plan : `one-moov-api` (web
   FastAPI) + `one-moov-db` (Postgres). Cliquer « **Apply** ».
4. **Poser les secrets.** Dans l'onglet **Environment** du service
   `one-moov-api`, remplir les variables marquées `sync: false` :

   | Variable | Où l'obtenir |
   |---|---|
   | `GROQ_API_KEY` | [console.groq.com/keys](https://console.groq.com/keys) — gratuit |
   | `RNCP_LLM_API_KEY` | [perplexity.ai/settings/api](https://www.perplexity.ai/settings/api) — 5 $/mois |
   | `CINETPAY_API_KEY`, `CINETPAY_SITE_ID` | Console CinetPay (production ou sandbox) |
   | `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` | Provider SMTP (Sendinblue, Mailgun, Amazon SES…) |

   Sans ces clés, l'app tourne en mode démo (guidé + repli local). Le
   déploiement fonctionne malgré tout.

5. Attendre que le service passe **Live** (~5 minutes le premier coup). Vérifier :

   ```bash
   curl https://one-moov-api.onrender.com/health
   # → {"status":"ok","llm_actif":true|false,"modeles":[...]}
   ```

6. **URL de l'API :** Render assigne un domaine du type
   `https://one-moov-api.onrender.com`. **Copier cette URL** — elle sert au
   déploiement Cloudflare.

**Auto-déploiement :** `autoDeploy: true` dans `render.yaml` : chaque push
sur la branche connectée redéploie automatiquement.

**Note plan gratuit :** le service s'endort après 15 minutes sans trafic.
Le premier appel réveille le container (~30 s). Pour éviter cet
endormissement, passer au plan Starter (7 $/mois).

---

## 2. Frontend — Cloudflare Pages (5 minutes actives, ~2 minutes de build)

Cloudflare Pages sert le front sur son CDN mondial, gratuit et rapide
même depuis l'Afrique centrale. Le PWA (manifest + service worker) est
déjà en place dans `frontend/public/` : l'étudiant peut « installer »
One Moov sur son téléphone depuis Chrome / Safari.

**Étapes :**

1. **Compte Cloudflare.** [dash.cloudflare.com/sign-up](https://dash.cloudflare.com/sign-up).
2. **Workers & Pages** → **Create application** → **Pages** →
   **Connect to Git**.
3. Sélectionner le dépôt `NANGUI123/one-moov`.
4. Renseigner les paramètres de build :

   | Champ | Valeur |
   |---|---|
   | **Framework preset** | `Vite` (auto-détecté) |
   | **Build command** | `npm run build` |
   | **Build output directory** | `dist` |
   | **Root directory** | `frontend` |
   | **Environment variable** | `VITE_API_URL` = `https://one-moov-api.onrender.com` (l'URL copiée à l'étape 6 du back) |
   | **Node version** | 20 |

5. **Save and deploy.** Cloudflare build le front et le publie sur
   `https://one-moov.pages.dev` (ou un sous-domaine similaire).

6. **Mettre à jour l'URL Render** dans deux fichiers si votre service
   Render a un nom différent :

   * `frontend/public/_redirects` (proxy `/api/*` vers le back)
   * `frontend/public/_headers` (CSP `connect-src`)

   Pousser le commit → Cloudflare rebuild automatiquement.

**Domaine personnalisé.** Dans les paramètres du projet Pages : « Custom
domains » → ajouter `app.onemoov.io` (ou l'équivalent). Cloudflare pose
le CNAME et le certificat SSL.

---

## 3. Vérification bout-en-bout

1. Ouvrir `https://one-moov.pages.dev` sur mobile.
2. Chrome propose « Installer l'application » → tap → l'icône One Moov
   arrive sur l'écran d'accueil.
3. Créer un compte : l'inscription doit répondre, `Bearer` reçu.
4. Lancer une orientation : la conversation démarre, en mode IA si les
   clés sont posées, en mode guidé sinon.
5. Vérifier le RNCP sur une école (« EPITA », « Master Data Science ») :
   la réponse arrive avec sa source.
6. Ouvrir l'onglet **Network** de Chrome DevTools → tous les appels vont
   sur `one-moov-api.onrender.com` via le reverse-proxy Cloudflare, ou
   directement si `VITE_API_URL` est renseigné.

---

## 4. Ce que je surveille en prod

Sur Render :

* **Logs** du service — les tokens et coûts LLM y sont écrits par
  `token_meter.record()`.
* `/api/me/costs` — coût cumulé de l'étudiant courant.
* `/api/admin/costs` — vue globale (à protéger derrière une auth admin
  avant de rendre l'endpoint public).

Sur Cloudflare :

* **Analytics** — trafic par pays et par route.
* **Speed** — Core Web Vitals du PWA.

Sur les fournisseurs LLM :

* Console Groq — quota par minute, dérive du prix.
* Console Perplexity — appels RNCP (petit volume, on ne devrait pas
  dépasser).

---

## 5. Rollback

**Render** : chaque déploiement est archivé. Onglet **Deploys** →
sélectionner un ancien déploiement → **Rollback to this deploy**. La
base Postgres n'est pas rollbackée (les migrations sont additives —
aucun ALTER DROP dans le schéma actuel).

**Cloudflare Pages** : chaque build est un déploiement isolé. Onglet
**Deployments** → **Rollback** sur n'importe quel build passé, en une
minute.

---

## 6. Le mode démo total

Si tu veux montrer le produit sans **aucune** clé configurée :

1. Ne pas remplir les secrets sur Render.
2. `GROQ_API_KEY` vide → conseiller + chatbot en mode guidé (répond
   quand même).
3. `RNCP_LLM_API_KEY` vide → repli sur l'export local RNCP (répond
   quand même).
4. `CINETPAY_API_KEY` vide → paiement en sandbox (bouton « J'ai payé »
   qui simule la confirmation).
5. `SMTP_HOST` vide → le lien de vérification s'affiche à l'écran au
   lieu de partir par mail (idéal pour tester sans e-mail).

L'application reste **utilisable de bout en bout** dans ce mode. C'est
la garantie de fiabilité qu'on tient : la fonctionnalité passe avant la
présence de l'IA.
