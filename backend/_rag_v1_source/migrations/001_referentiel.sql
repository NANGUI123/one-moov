-- ============================================================================
-- Référentiel : villes, domaines, établissements.
--
-- Ces données sont structurées, donc elles vivent en base, pas dans le RAG.
-- Le matching s'appuie sur des filtres durs (budget, niveau, langue) que seul
-- SQL peut garantir : une école hors budget ne doit jamais remonter, quelle
-- que soit sa proximité sémantique avec le projet de l'étudiant.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- --- Types -------------------------------------------------------------

DO $$ BEGIN
    CREATE TYPE type_etablissement AS ENUM ('universite','ecole_ingenieur','ecole_commerce','iut','bts','autre');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE niveau_diplome AS ENUM ('licence','master','doctorat','autre');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE langue_ens AS ENUM ('francais','anglais','bilingue');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE type_formation AS ENUM ('initiale','alternance','continue');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE secteur_etablissement AS ENUM ('public','prive');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- --- Villes ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ville (
    id                   SERIAL PRIMARY KEY,
    nom                  TEXT NOT NULL UNIQUE,
    region               TEXT NOT NULL,
    cout_vie_mensuel     NUMERIC(6,0) NOT NULL,   -- € hors loyer
    loyer_moyen_studio   NUMERIC(6,0) NOT NULL,   -- €/mois
    population_etudiante INTEGER,
    reseau_diaspora      BOOLEAN NOT NULL DEFAULT FALSE,
    description          TEXT NOT NULL DEFAULT '',
    -- Traçabilité : d'où vient le chiffre, et quand a-t-il été vérifié.
    source               TEXT NOT NULL DEFAULT 'INSEE',
    verifie_le           DATE NOT NULL DEFAULT CURRENT_DATE
);

-- --- Domaines ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS domaine (
    id        SERIAL PRIMARY KEY,
    code      TEXT NOT NULL UNIQUE,
    libelle   TEXT NOT NULL,
    parent_id INTEGER REFERENCES domaine(id)
);

-- --- Établissements ----------------------------------------------------

CREATE TABLE IF NOT EXISTS etablissement (
    id                  TEXT PRIMARY KEY,
    nom                 TEXT NOT NULL,
    type                type_etablissement NOT NULL,
    secteur             secteur_etablissement NOT NULL,
    ville_id            INTEGER NOT NULL REFERENCES ville(id),

    -- Filtres durs : ces colonnes décident de l'éligibilité, sans discussion.
    niveaux_acceptes    niveau_diplome[] NOT NULL,
    formations_acceptees type_formation[] NOT NULL DEFAULT ARRAY['initiale']::type_formation[],
    langue              langue_ens NOT NULL,
    frais_scolarite_an  NUMERIC(7,0) NOT NULL,
    niveau_fr_requis    TEXT,
    connecte_cf         BOOLEAN NOT NULL DEFAULT TRUE,

    -- Classement souple : recherche sémantique et plein texte.
    description         TEXT NOT NULL,
    site_web            TEXT,
    embedding           vector(1024),
    fts                 tsvector GENERATED ALWAYS AS (
                          to_tsvector('french', coalesce(nom,'') || ' ' || coalesce(description,''))
                        ) STORED,

    source              TEXT NOT NULL DEFAULT 'site officiel de l''établissement',
    verifie_le          DATE NOT NULL DEFAULT CURRENT_DATE
);

CREATE TABLE IF NOT EXISTS etablissement_domaine (
    etablissement_id TEXT NOT NULL REFERENCES etablissement(id) ON DELETE CASCADE,
    domaine_id       INTEGER NOT NULL REFERENCES domaine(id),
    PRIMARY KEY (etablissement_id, domaine_id)
);

-- --- Index -------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_etab_fts       ON etablissement USING GIN (fts);
CREATE INDEX IF NOT EXISTS idx_etab_nom_trgm  ON etablissement USING GIN (nom gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_etab_embedding ON etablissement USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_etab_filtres   ON etablissement (secteur, langue, frais_scolarite_an, connecte_cf);
CREATE INDEX IF NOT EXISTS idx_etab_niveaux   ON etablissement USING GIN (niveaux_acceptes);

-- ============================================================================
-- Construction de la requête lexicale, utilisée par le matching et par le RAG.
--
-- plainto_tsquery relie tous les mots par ET. Sur une question écrite
-- naturellement, « quelles pièces pour mon dossier », cela exige que chaque
-- mot figure dans le texte cible, et plus rien ne remonte. Le problème est le
-- même avec un récit d'étudiant de plusieurs phrases.
--
-- On découpe donc le texte en lexèmes, ce qui retire les mots vides et
-- applique la racinisation française, puis on les relie par OU. Le classement
-- par ts_rank_cd fait remonter les textes qui couvrent le plus de termes.
-- ============================================================================

CREATE OR REPLACE FUNCTION requete_ou(p_texte TEXT)
RETURNS tsquery AS $$
DECLARE
    lexemes TEXT;
BEGIN
    SELECT array_to_string(
             tsvector_to_array(to_tsvector('french', COALESCE(p_texte, ''))),
             ' | '
           )
    INTO lexemes;

    IF lexemes IS NULL OR lexemes = '' THEN
        RETURN NULL;   -- un texte fait uniquement de mots vides
    END IF;

    RETURN to_tsquery('french', lexemes);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ============================================================================
-- Matching hybride.
--
-- Deux temps, et l'ordre compte :
--   1. Filtres DURS en SQL. Éligibilité non négociable.
--   2. Classement SOUPLE sur le sous-ensemble éligible : fusion RRF entre
--      la similarité vectorielle et la pertinence plein texte.
--
-- Si l'embedding est NULL (modèle non chargé), le classement dégrade
-- proprement sur le plein texte seul, sans erreur.
-- ============================================================================

CREATE OR REPLACE FUNCTION matcher_etablissements(
    p_niveau      niveau_diplome,
    p_formation   type_formation,
    p_langue      langue_ens,
    p_budget_an   NUMERIC,
    p_secteurs    secteur_etablissement[],
    p_embedding   vector(1024),
    p_narratif    TEXT,
    p_limit       INTEGER DEFAULT 8
)
RETURNS TABLE (
    etablissement_id TEXT,
    nom TEXT,
    ville TEXT,
    secteur secteur_etablissement,
    frais NUMERIC,
    description TEXT,
    site_web TEXT,
    verifie_le DATE,
    score NUMERIC
) AS $$
WITH eligibles AS (
    SELECT e.id, e.nom, v.nom AS ville, e.secteur, e.frais_scolarite_an,
           e.description, e.site_web, e.verifie_le, e.embedding, e.fts
    FROM etablissement e
    JOIN ville v ON v.id = e.ville_id
    WHERE p_niveau = ANY (e.niveaux_acceptes)
      AND p_formation = ANY (e.formations_acceptees)
      AND (e.langue = p_langue OR e.langue = 'bilingue')
      AND e.frais_scolarite_an <= p_budget_an
      AND e.secteur = ANY (p_secteurs)
),
rang_vecteur AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> p_embedding) AS rang
    FROM eligibles
    WHERE p_embedding IS NOT NULL AND embedding IS NOT NULL
),
rang_texte AS (
    SELECT id, ROW_NUMBER() OVER (
             ORDER BY ts_rank_cd(fts, requete_ou(p_narratif)) DESC
           ) AS rang
    FROM eligibles
    WHERE p_narratif IS NOT NULL AND p_narratif <> ''
      AND requete_ou(p_narratif) IS NOT NULL
),
fusion AS (
    SELECT e.id,
           COALESCE(1.0 / (60 + rv.rang), 0) + COALESCE(1.0 / (60 + rt.rang), 0) AS score
    FROM eligibles e
    LEFT JOIN rang_vecteur rv ON rv.id = e.id
    LEFT JOIN rang_texte   rt ON rt.id = e.id
)
SELECT e.id, e.nom, e.ville, e.secteur, e.frais_scolarite_an,
       e.description, e.site_web, e.verifie_le,
       ROUND(f.score::numeric, 5)
FROM fusion f
JOIN eligibles e ON e.id = f.id
ORDER BY f.score DESC, e.frais_scolarite_an ASC
LIMIT p_limit;
$$ LANGUAGE sql STABLE;
