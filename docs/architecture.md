# One Moov — Parcours bout-en-bout

Ce document reprend le schéma d'architecture fourni en PDF, en texte et avec
les points d'ancrage dans le code de ce dépôt.

Deux acteurs, un système :

```
Étudiant (mobile / navigateur)
        ↕
   ┌──────────────────────────────────────────┐
   │        One Moov (React + FastAPI)        │
   │  base SQL + RAG hybride + orchestrateur  │
   └──────────────────────────────────────────┘
        ↕
Services tiers : LLM (Groq, Perplexity), paiement (CinetPay), WhatsApp,
open data (ONISEP, France Compétences, Mon Master, Parcoursup).
```

Flèches pleines : **synchrones** (requête → réponse immédiate).
Flèches pointillées : **asynchrones** (webhook, notification, tâche de fond).

---

## Inscription et première piste

### 1. Inscription (prénom, e-mail, WhatsApp)

`POST /api/auth/register`
Le client envoie prénom + e-mail + mot de passe. L'API stocke le prénom,
l'e-mail en clair (pour la connexion) et l'empreinte bcrypt du mot de
passe. Rien d'autre.

### 2. Vérification e-mail / SMS (code à usage unique)

`POST /api/auth/verify` (avec le lien reçu par e-mail).
Un jeton à usage unique est envoyé. Sans SMTP configuré, il apparaît dans
les journaux du serveur (mode démo) ; sinon un vrai courrier part.

**Le numéro WhatsApp** est capturé dès l'inscription pour servir aux
rappels d'échéances (voir étape 13).

---

## Orientation gratuite

### 3. Créer une piste (pays cible) et lancer l'orientation

`POST /api/pistes {"pays": "Cameroun"}`

### 4. RAG — passages officiels pertinents

`app/services/rag.py:rechercher()`
Chaque appel du conseiller déclenche une recherche hybride :

* **Lexicale** : intersection de tokens (BM25-approximatif, sans dépendance
  à `pg_trgm`).
* **Dense** : cosinus sur les embeddings, si un fournisseur est
  configuré (Mistral, OpenAI, local).
* **Fusion** : Reciprocal Rank Fusion (`k = 60`).

Les passages proviennent de trois sources : le corpus procédural
d'amorçage (`app/donnees/procedures.json`), le catalogue de formations
enrichi, et les fiches RNCP synchronisées. Chaque passage porte son
`organisme`, son `url_officielle`, sa `version`.

### 5. Scoring déterministe (budget · niveau · RNCP)

`app/services/orientation_engine.py:top_formations()`
Ce sont des règles explicables, pas un modèle. Pondération :

* domaine 40 pts
* niveau visé 25 pts
* budget 20 pts
* ville souhaitée 12 pts
* voie (public / privé) 6 pts

Les formations viennent de la table `formations` (jamais du LLM).
`explication` cite les raisons du score, ce qui est affiché à l'étudiant.

### 6. Mise en forme du texte du rapport — LLM Groq

`app/routers/orientation.py:_synthese()`
Le LLM reçoit le **profil déjà validé** et produit uniquement la synthèse
(2-3 phrases), les atouts, les points d'attention, la prochaine étape. Il
ne choisit ni ne classe aucune école, aucune ville, aucun montant.

### 7. Conversation empathique → rapport d'orientation (gratuit)

`POST /api/orientation/chat` puis `POST /api/orientation/rapport`
La conversation vise 7-8 échanges couvrant : parcours, motivation,
domaine, projet France, projet pro, niveau, budget/financement, ville,
long terme. Elle se termine par le marqueur `[[PRET]]` que le front lit
pour proposer le bouton « Générer mon rapport ».

Depuis la fusion, le prompt système du conseiller reçoit **3 passages
RAG pertinents** en plus (extrait du dernier message étudiant → recherche
→ injection dans le prompt). Le conseiller reste maître du fil, mais ses
conseils sont ancrés dans du réel.

---

## Passage à la feuille de route — payant

### 8. Choix voie + méthode (mobile money)

`POST /api/roadmap/voie {"voie": "public" | "prive"}`
En voie privée, un formulaire supplémentaire ouvre la vérification RNCP
(exigence 4 du cahier des charges) :

`POST /api/rncp/verify {"intitule", "etablissement", "code_rncp"}`

Deux moteurs cascadent :

1. **LLM connecté au web** (`app/services/rncp_web.py`, par défaut
   Perplexity sonar) — renvoie nom du titre, numéro, niveau, date
   d'échéance, statut. Le prompt interdit l'invention.
2. Si `RNCP_LLM_API_KEY` est absente ou l'appel échoue → **repli** sur
   l'export officiel synchronisé localement
   (`app/services/rncp_client.py`).

### 9. Créer une session de paiement hébergée

`POST /api/paiement/create` → renvoie une URL CinetPay. L'étudiant paie
sur la page sécurisée du fournisseur ; aucune donnée bancaire ne
transite par One Moov.

### 10. Paiement mobile money (Orange Money · Wave · MTN)

Hors One Moov. L'étudiant valide sur la page hébergée.

### 11. Webhook de confirmation (signé, idempotent) → accès ouvert

CinetPay → `POST /api/paiement/webhook`. La signature est vérifiée, le
statut est mis à jour, la piste passe `paid=True`. Idempotent :
plusieurs livraisons du même webhook produisent le même effet.

---

## Feuille de route et suivi

### 12. Feuille de route — vue arbre, échéances, prochaine action

`POST /api/roadmap/generate` puis `GET /api/pistes/{id}`.
L'arbre est construit par niveaux de dépendance
(`app/services/roadmap_engine.py`). Chaque étape a une échéance conseillée,
un statut (`verrouille` / `ouvert` / `fait`) et une urgence
(`retard` / `bientot` / `avenir` / `fait`). Les étapes critiques sont
marquées ; les valider demande une confirmation supplémentaire.

Le **chatbot** (`POST /api/chatbot`) est débloqué en même temps que la
feuille de route. Il reçoit :

* le contexte de l'étape en cours ;
* **les passages RAG pertinents pour la question posée**, filtrés par
  phase (candidature / entretien / visa / logement / arrivée) ;
* les faits vérifiés associés (montants, délais).

Le LLM doit citer `[1]` `[2]` ; l'API renvoie les vraies sources dans le
champ `sources` de la réponse.

### 13. Rappels WhatsApp J-3 des étapes critiques

Tâche de fond planifiée : 3 jours avant chaque étape critique non
faite, un message part vers le numéro capturé à l'étape 1.

---

## En continu — tâches de fond

### 14. ETL des sources officielles

`scripts/enrichir_formations_web.py` ingère 4 sources en cascade,
chacune avec un instantané local de repli :

* **ONISEP Idéo** (public) — annuaire des formations
* **Mon Master** (public) — référentiel des mentions master
* **Parcoursup** (public) — fiches formations post-bac
* **Écoles privées** (partenariats) — snapshot local

`scripts/ingerer_rag.py` reconstitue ensuite la base vectorielle à
partir de la table `formations`, du corpus procédural et des fiches
RNCP synchronisées.

`scripts/ingerer_rncp.py` synchronise l'export officiel de France
Compétences (`FRANCE_COMPETENCES_BASE` dans `config.py`).

---

## Le fil rouge de la fiabilité

```
Front sans logique sensible
    → API qui vérifie tout
        → RAG + scoring qui fournit les faits
            → LLM qui met en forme
                → sources officielles synchronisées.
```

À aucun moment un fait ne sort du modèle seul. C'est cette discipline
qui distingue One Moov d'un simple assistant conversationnel : chaque
chiffre, chaque date, chaque code RNCP porte sa source et sa date de
vérification.
