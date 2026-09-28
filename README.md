# One Moov

Accompagnement des étudiants d'Afrique francophone (Cameroun, Congo-Brazzaville…)
vers les études en France : orientation gratuite, feuille de route personnalisée,
chatbot procédural sourcé, entretien Campus France blanc, aide à la contestation
d'un refus.

> Ce dépôt fusionne deux projets internes :
>
> * `one_moov_v1` — le **front React** propre et le socle **API FastAPI**
>   (auth JWT + vérification e-mail, orientation, roadmap, paiement CinetPay,
>   chatbot, aides IA, vérification RNCP par LLM connecté au web).
> * `One_Moov_RAG_V1_Integration` — la **couche RAG hybride** (procédures
>   officielles, faits vérifiés, fusion lexicale + vectorielle) et son
>   corpus procédural d'amorçage.
>
> Résultat : le front V1 branché sur un back V1 enrichi d'un **conseiller
> d'orientation RAG-aware** et d'un **chatbot qui cite ses sources**.

---

## Le principe qui gouverne le reste

> **Les faits critiques vivent en base. Le procédural explicatif vit dans le RAG.
> Le LLM propose, la donnée fait autorité.**

Un montant, un délai, un seuil de ressources, un code RNCP ne sont jamais produits
par le modèle. Ils viennent d'une table (`formations`, `rncp_fiches`) ou d'un
passage indexé, avec leur source et leur date de vérification. Le LLM rédige
l'explication autour, à partir de passages officiels qu'il **doit citer** avec
`[1]` `[2]` : l'interface transforme ces numéros en vraies références.

C'est la réponse à la faiblesse connue des agents : un modèle interrogé sur le
montant du compte bloqué produira un chiffre plausible et faux, avec le même
aplomb qu'un vrai. Un étudiant qui organise son départ sur ce chiffre perd son
dossier.

---

## Le parcours bout-en-bout

Repris du schéma d'architecture (`docs/architecture.md`) :

| Étape | Acteur | Où |
|-------|--------|----|
| 1  Inscription (prénom, e-mail, WhatsApp) | Étudiant → API | `POST /api/auth/register` |
| 2  Vérification e-mail (code à usage unique) | API → SMTP / démo | `POST /api/auth/verify` |
| 3  Nouvelle piste (pays cible) | Étudiant → API | `POST /api/pistes` |
| 4  **RAG** — passages officiels pertinents (`pgvector`-compatible) | API interne | `services/rag.py` |
| 5  Scoring déterministe (domaine 40 · niveau 25 · budget 20 · ville 12 · voie 6) | API interne | `services/orientation_engine.py` |
| 6  Mise en forme du rapport par le LLM (jamais décideur) | API → Groq | `POST /api/orientation/rapport` |
| 7  Conversation empathique → rapport d'orientation (gratuit) | Étudiant ↔ API | `POST /api/orientation/chat` |
| 8  Choix voie + méthode (mobile money) | Étudiant → API | `POST /api/roadmap/voie` |
| 9  Session de paiement hébergée | API → CinetPay | `POST /api/paiement/create` |
| 10 Paiement mobile money (aucune donnée bancaire chez nous) | Étudiant → CinetPay | (hébergée) |
| 11 Webhook signé → accès ouvert | CinetPay → API | `POST /api/paiement/webhook` |
| 12 Feuille de route : arbre, échéances, prochaine action | Étudiant ↔ API | `POST /api/roadmap/generate` |
| 13 Rappels WhatsApp J-3 des étapes critiques (asynchrone) | API → WhatsApp | tâche de fond |
| 14 ETL open data (ONISEP, France Compétences, Mon Master, Parcoursup) | API interne, continu | `scripts/enrichir_formations_web.py` |

Les étapes 4-5 se passent **à l'intérieur** de One Moov : c'est là que la
fiabilité se joue. Les flèches asynchrones (11, 13, 14) arrivent quand
l'événement se produit, pas pendant que l'étudiant attend.

---

## Ce que la fusion a apporté

**Un conseiller d'orientation avec RAG** (exigence 3)
Le prompt système reçoit désormais 3 passages officiels pertinents en plus
du dernier message étudiant. Le conseiller reste maître du fil, mais ses
conseils sont ancrés dans du réel — plus d'hallucinations sur une
procédure. `app/routers/orientation.py:chat()`.

**Un chatbot qui cite ses sources**
Le chatbot prémium reçoit lui aussi les passages officiels ; il doit citer
`[1]` `[2]` ; l'API renvoie les vraies références (`sources` dans la
réponse). `app/routers/chatbot.py:chatbot()`.

**Un RAG multi-source** (exigences 2, 5, 7)
`app/services/rag.py` construit une base vectorielle hybride
(BM25-approximatif + cosinus sur embeddings) qui tourne sur SQLite en dev
et PostgreSQL en prod, sans exiger `pgvector`. Trois sources sont ingérées :

* Le corpus procédural (Études en France, VLS-TS, entretien, logement,
  arrivée, contestation) → `app/donnees/procedures.json` — **24 passages**.
* Le catalogue de formations enrichi via l'ETL → **1 passage par formation**.
* Les fiches RNCP synchronisées → **1 passage par fiche**.

**Un enrichissement web des formations** (exigence 2)
`scripts/enrichir_formations_web.py` ingère depuis 4 sources en cascade,
chacune avec un snapshot local de repli quand l'open data est
inaccessible :

* ONISEP Idéo (public)
* Mon Master (public)
* Parcoursup (public)
* Écoles privées reconnues (snapshot local, à enrichir au fil des partenariats)

**Une vérification RNCP LLM + web** (exigence 4)
Elle était déjà présente dans V1 (`app/services/rncp_web.py`). L'utilisateur
saisit école + formation → un LLM connecté au web (Perplexity « sonar » par
défaut, OpenAI-compatible) recherche la fiche officielle sur
francecompetences.fr et renvoie : nom du titre, code RNCP, niveau, date
d'échéance, statut. Repli automatique sur l'export officiel synchronisé
localement si aucune clé n'est configurée.

---

## Démarrer en local

**Backend** (Python 3.11+)

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env               # renseigner GROQ_API_KEY, RNCP_LLM_API_KEY, etc.
uvicorn app.main:app --reload --port 8000
```

Au premier démarrage :

* le schéma SQL se crée (SQLite par défaut, sinon `DATABASE_URL`) ;
* les tables RAG (`rag_documents`, `rag_passages`) s'initialisent ;
* l'application est utilisable en **mode guidé** sans aucune clé.

**Peupler la base vectorielle et le catalogue de formations**

```bash
cd backend
python -m scripts.enrichir_formations_web        # ONISEP + Mon Master + privé
python -m scripts.ingerer_rag                    # 24 passages procéduraux + 1 par formation
python -m scripts.ingerer_rag --sans-embedding   # plus rapide, lexical seul
```

**Frontend** (Node 18+)

```bash
cd frontend
npm install
npm run dev                                       # http://localhost:5173
```

Vite proxifie `/api` vers `http://localhost:8000` ; aucune configuration
supplémentaire.

**Tout d'un coup**

```bash
./start.sh
```

Lance backend + frontend, ingère les formations et le RAG au premier démarrage.

---

## Configuration essentielle (`.env`)

```env
DATABASE_URL=                        # vide → SQLite local
GROQ_API_KEY=                        # LLM principal (Llama 3.3 70B via Groq)
RNCP_LLM_API_KEY=                    # LLM connecté au web (Perplexity sonar par défaut)
RNCP_LLM_BASE_URL=https://api.perplexity.ai
RNCP_LLM_MODEL=sonar
CINETPAY_API_KEY=                    # paiement mobile money — sinon mode sandbox
SMTP_HOST=                           # sans SMTP → mode démo (lien dans les logs)
JWT_SECRET=change-me-in-production
```

Sans aucune clé, l'application tourne en mode guidé + repli local, avec le
message adapté à l'écran.

---

## Organisation du dépôt

```
backend/
  app/
    main.py                     init DB + init tables RAG + orchestrateur LLM
    routers/                    auth, pistes, orientation, roadmap, rncp,
                                paiement, chatbot, aides, metrics
    services/
      rag.py                    RAG hybride portable (SQLite / Postgres)
      embeddings.py             encoder Mistral/OpenAI/local (optionnel)
      orientation_engine.py     scoring déterministe des 10 formations
      roadmap_engine.py         arbre d'étapes, échéances, urgences
      rncp_web.py               vérification RNCP par LLM + accès web
      rncp_client.py            repli sur l'export officiel local
      llm.py                    orchestrateur Groq à cascade de modèles
      mailer.py                 SMTP (avec repli console de démo)
      cinetpay.py               session de paiement + webhook signé
    data/
      ingestion/onisep.py       ingestion open data
      ingestion/rncp.py         synchronisation fiches France Compétences
      seed/                     snapshots locaux (repli hors ligne)
      procedures/france.py      procédures officielles structurées
    donnees/procedures.json     corpus procédural d'amorçage (RAG)
    prompts.py                  prompts du conseiller, extracteur, entretien
    models.py                   SQLAlchemy 2.0 (User, Piste, Formation, RncpFiche…)
    schemas.py                  Pydantic (ChatIn, FormationsIn, RncpVerifyIn…)
  scripts/
    ingerer_rag.py              peuple rag_passages depuis procedures + formations + RNCP
    enrichir_formations_web.py  ONISEP + Mon Master + Parcoursup + écoles privées
    ingerer_rncp.py             sync export France Compétences
  _rag_v1_source/               source originale du projet 2 conservée pour référence
                                (migrations pgvector, agents/, scripts_rag/, tests/)
frontend/
  src/
    App.jsx                     tous les écrans (Auth, Dashboard, Orientation,
                                Rapport, Parcours, Roadmap, Entretien, Contestation)
    api.js                      client fetch + JWT localStorage
    styles.js                   thème sombre, tokens de couleur
    main.jsx                    montage React + CSS global
  vite.config.js                proxy /api → localhost:8000
docs/
  architecture.md               parcours bout-en-bout du PDF, en texte
start.sh                        lance backend + frontend
```

Le répertoire `_rag_v1_source/` contient le back du projet 2 dans son état
d'origine (migrations pgvector, module `services/rag.py` d'origine avec la
fonction SQL `rechercher_passages`, agents `intake` / `matching` / `chatbot` /
`entretien`, tests). Il est conservé pour référence — la couche RAG portée
sur SQLite/Postgres vit désormais dans `app/services/rag.py`.

---

## Les données de l'étudiant

| Conservé | Jamais conservé |
|---|---|
| Adresse e-mail | **Les conversations avec les agents** |
| Empreinte bcrypt du mot de passe | Nom, adresse postale, documents |
| Projet d'études, feuille de route, progression | Coordonnées bancaires |

Les conversations ne quittent jamais l'appareil (localStorage). La suppression
d'un compte est un `DELETE` avec cascade — pas d'effacement logique, pas de
corbeille.

---

## Ce qui reste à faire avant un usage réel

* Vérifier un par un les montants et délais amorcés (les scripts d'ingestion
  vont chercher les vraies valeurs, mais les snapshots de repli restent des
  copies figées).
* Brancher un SMTP réel (`SMTP_HOST`) — sans lui, la vérification d'e-mail
  tombe en mode démo (lien affiché à l'écran).
* Configurer `RNCP_LLM_API_KEY` (Perplexity) pour la vérification RNCP par le
  web — sinon repli sur l'export local.
* Faire tourner `python -m scripts.ingerer_rncp` avec un accès sortant pour
  synchroniser le vrai référentiel France Compétences.
* Brancher CinetPay (`CINETPAY_API_KEY`) — sinon le paiement reste en
  sandbox.
* Brancher WhatsApp Business pour les rappels J-3 des étapes critiques.

---

Voir `docs/architecture.md` pour le déroulé bout-en-bout, et le
[PDF d'architecture](docs/) fourni à l'appui.
