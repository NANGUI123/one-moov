# One Moov

Accompagnement des étudiants du Cameroun et du Congo-Brazzaville vers les
études en France, de l'orientation jusqu'aux premières semaines sur place.

Deux agents : un agent d'orientation, qui construit le profil et produit une
feuille de route ; un chatbot prémium, débloqué après la feuille de route,
qui répond aux questions de procédure en citant ses sources et prépare à
l'entretien.



---

## Le principe qui gouverne le reste

> **Le factuel critique va en base SQL. Le procédural explicatif va au RAG.
> Le modèle propose, la donnée fait autorité.**

Un montant, un délai, un seuil de ressources, un code RNCP ne sont jamais
produits par le modèle. Ils viennent d'une table, avec leur source et leur
date de vérification. Le modèle rédige l'explication autour, à partir de
passages officiels qu'il doit citer.

C'est la réponse à la faiblesse connue des agents conversationnels : un
modèle interrogé sur le montant du compte bloqué produira un chiffre
plausible et faux, avec le même aplomb que s'il était juste. Un étudiant qui
organise son départ sur ce chiffre perd son dossier.

---

## L'architecture

| Couche | Technologie | Rôle |
|---|---|---|
| Interface | React 18 + Vite 6, PWA | Écrans, conversation, installation sur le téléphone |
| API | FastAPI (Python 3.12) | Les deux agents, les comptes, les contrats de données |
| Modèle | Orchestrateur à 3 niveaux | Hugging Face → secours automatique → mode guidé sans IA |
| Connaissance | RAG sur PostgreSQL + pgvector | Les procédures officielles, citées en source |
| Référentiel | PostgreSQL 16 | Villes, établissements, faits vérifiés, fiches RNCP |
| Comptes | JWT + scrypt | Retrouver son parcours d'un téléphone à l'autre |

Le détail des choix, et surtout des options écartées, est dans
[`docs/One-Moov-fiche-technique.docx`](docs/).

---

## Démarrer en local

### Tout d'un coup, avec Docker

```bash
cd backend
docker compose up --build
```

L'API écoute sur `http://localhost:8000`, la documentation sur `/api/docs`.
Les migrations et l'ingestion du RAG tournent au démarrage.

### À la main

**La base.** PostgreSQL 16 avec les extensions `pgvector`, `pg_trgm` et
`unaccent`. `pgvector` est nécessaire même quand les embeddings sont
désactivés : les colonnes vectorielles font partie du schéma.

```bash
cd backend
pip install -r requirements.txt
cp .env.exemple .env          # puis renseigner DATABASE_URL
python -m scripts.migrer      # applique les 7 migrations
python -m scripts.ingerer_rag # charge les 30 passages
./lancer_dev.sh               # ou : uvicorn app.main:app --reload
```

**L'interface.**

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173, /api relayé vers le port 8000
```

Sans aucune clé de modèle, l'application tourne en **mode guidé** : moins
fluide, mais complète. C'est le mode à utiliser pour une démonstration si
les clés ne sont pas prêtes.

---

## Les tests

```bash
cd backend
python -m scripts.tester          # 80 vérifications : base, agents, orchestrateur, quotas, RNCP
python -m scripts.tester_comptes  # 29 vérifications : cycle de vie complet d'un compte
```

`tester_comptes` suppose l'API lancée et le SMTP non configuré : il relit le
code de vérification dans le journal du serveur. Il tape bien plus vite
qu'un humain, donc il faut desserrer les quotas :

```bash
QUOTA_RAFALE=500 QUOTA_HORAIRE=5000 QUOTA_MODELE_HORAIRE=3000 ./lancer_dev.sh
```

Ce que les tests couvrent, au-delà du fonctionnel :

- aucun montant inventé n'apparaît dans le texte d'une feuille de route ;
- la notation d'entretien est reproductible ;
- la bascule de l'orchestrateur a bien lieu (deux faux fournisseurs montés
  pendant le test, le premier tombe toujours) ;
- aucune table ni colonne ne peut stocker une conversation ;
- la suppression d'un compte emporte vraiment toutes ses données.

---

## Déployer

Voir [`DEPLOIEMENT.md`](DEPLOIEMENT.md). En résumé : l'API et la base sur
Render (le `render.yaml` à la racine crée les deux), l'interface sur
Cloudflare Pages.

Cloudflare Pages exécute du JavaScript sur les Workers, pas du Python, et ne
fournit pas de PostgreSQL : l'API ne peut pas y être hébergée. Pages sert
l'interface, qui appelle l'API hébergée ailleurs.

---

## Les données de l'étudiant

| Conservé | Jamais conservé |
|---|---|
| Adresse e-mail | **Les conversations avec les agents** |
| Empreinte scrypt du mot de passe | Nom, adresse postale, documents |
| Projet d'études, feuille de route, progression | Coordonnées bancaires |

Les conversations ne quittent jamais l'appareil, même pour un compte
connecté : elles vivent en `sessionStorage` et partent à la fermeture. Un
historique d'échanges en dit bien plus long sur quelqu'un qu'une liste de
champs.

Supprimer un compte est un `DELETE` avec cascade. Pas d'effacement logique,
pas de corbeille.

---

## À faire avant un usage réel

Ces points sont connus et assumés, pas oubliés :

- **Reconfirmer les valeurs amorcées.** Les montants et délais de
  `migrations/004_amorcage.sql` viennent de la spécification du projet. Ils
  doivent être vérifiés un par un sur les sites officiels.
- **Brancher un SMTP.** Sans lui, le code de vérification part dans les
  journaux du serveur : personne ne peut créer de compte seul.
- **Faire tourner `scripts/ingerer_rncp.py` une première fois** avec
  `--colonnes`. Il n'a pas pu être exécuté contre le vrai fichier pendant le
  développement, faute d'accès réseau sortant ; il refuse d'écrire tant
  qu'il ne reconnaît pas les colonnes.
- **Intégrer le paiement.** Il est simulé. CinetPay ou PayDunya restent à
  brancher.
- **Brancher WhatsApp.** Les alertes sont maquettées côté interface ;
  l'envoi suppose un compte WhatsApp Business.

---

## L'organisation du dépôt

```
backend/
  app/
    agents/agent1/      orientation : intake, matching, roadmap
    agents/agent2/      chatbot et simulation d'entretien
    routers/            orientation, chatbot, comptes, rncp, systeme
    services/           llm (orchestrateur), rag, faits, quotas, métriques, sécurité
    models/schemas.py   les contrats Pydantic à valeurs fermées
  migrations/           7 fichiers SQL, appliqués dans l'ordre
  scripts/              migrer, ingerer_rag, ingerer_rncp, veille_sources, tester
frontend/
  src/ecrans/           un fichier par écran
  src/composants/       BadgeSource, FaitVerifie, FicheRNCP portent la fiabilité
  src/lib/              client API et état
  public/               manifeste PWA, service worker, icônes
docs/                   la fiche technique
```
