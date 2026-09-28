-- ============================================================================
-- RAG : base de connaissance procédurale.
--
-- Ce qui va ici : le procédural qui évolue et qui s'explique en phrases.
-- Comment constituer un dossier, ce qu'attend un entretien, quelles pièces
-- pour un visa, comment chercher un logement.
--
-- Ce qui ne va PAS ici : les montants, les dates et les quotas. Ils sont en
-- table fait_critique, sourcés et datés. Le RAG explique la démarche, la base
-- fournit les chiffres.
--
-- Chaque document porte sa version. Quand une procédure change, on charge une
-- nouvelle version et on désactive l'ancienne. On sait ainsi sur quelle
-- version de la connaissance une réponse a été produite.
-- ============================================================================

CREATE TABLE IF NOT EXISTS document_source (
    id            SERIAL PRIMARY KEY,
    reference     TEXT NOT NULL,              -- ex : 'cf_procedure_eef'
    titre         TEXT NOT NULL,
    url_officielle TEXT NOT NULL,
    organisme     TEXT NOT NULL,              -- Campus France, France-Visas…
    pays          TEXT,                        -- NULL = tous pays
    version       INTEGER NOT NULL DEFAULT 1,
    actif         BOOLEAN NOT NULL DEFAULT TRUE,
    publie_le     DATE,
    ingere_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    empreinte     TEXT,                        -- hachage du contenu ingéré
    UNIQUE (reference, version)
);

CREATE INDEX IF NOT EXISTS idx_doc_actif ON document_source (reference) WHERE actif;

-- --- Passages ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS passage (
    id           SERIAL PRIMARY KEY,
    document_id  INTEGER NOT NULL REFERENCES document_source(id) ON DELETE CASCADE,
    ordre        INTEGER NOT NULL,
    titre        TEXT,                        -- intitulé de section
    contenu      TEXT NOT NULL,
    phase        TEXT,                        -- candidature | entretien | visa | logement…
    embedding    vector(1024),
    fts          tsvector GENERATED ALWAYS AS (
                   to_tsvector('french', coalesce(titre,'') || ' ' || contenu)
                 ) STORED,
    UNIQUE (document_id, ordre)
);

CREATE INDEX IF NOT EXISTS idx_passage_fts       ON passage USING GIN (fts);
CREATE INDEX IF NOT EXISTS idx_passage_embedding ON passage USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_passage_phase     ON passage (phase);

-- ============================================================================
-- Recherche hybride sur les passages.
-- La fonction requete_ou utilisée ici est définie dans 001_referentiel.sql.
--
-- Même principe que le matching des établissements : on fusionne un
-- classement dense (embeddings) et un classement lexical (plein texte)
-- par Reciprocal Rank Fusion.
--
-- Pourquoi les deux : la recherche dense comprend la reformulation
-- ("comment prouver que j'ai assez d'argent" retrouve un passage sur les
-- ressources), la recherche lexicale retrouve les termes exacts que la
-- recherche dense rate ("formulaire 15984*01", "VLS-TS").
-- ============================================================================

CREATE OR REPLACE FUNCTION rechercher_passages(
    p_embedding  vector(1024),
    p_requete    TEXT,
    p_phase      TEXT DEFAULT NULL,
    p_pays       TEXT DEFAULT NULL,
    p_candidats  INTEGER DEFAULT 20,
    p_limit      INTEGER DEFAULT 5
)
RETURNS TABLE (
    passage_id INTEGER,
    titre TEXT,
    contenu TEXT,
    phase TEXT,
    document_titre TEXT,
    organisme TEXT,
    url_officielle TEXT,
    version INTEGER,
    score NUMERIC
) AS $$
WITH candidats AS (
    SELECT p.id, p.titre, p.contenu, p.phase, p.embedding, p.fts,
           d.titre AS doc_titre, d.organisme, d.url_officielle, d.version
    FROM passage p
    JOIN document_source d ON d.id = p.document_id
    WHERE d.actif
      AND (p_phase IS NULL OR p.phase = p_phase)
      AND (p_pays IS NULL OR d.pays IS NULL OR d.pays = p_pays)
),
rang_dense AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> p_embedding) AS rang
    FROM candidats
    WHERE p_embedding IS NOT NULL AND embedding IS NOT NULL
    LIMIT p_candidats
),
rang_lexical AS (
    SELECT id, ROW_NUMBER() OVER (
             ORDER BY ts_rank_cd(fts, requete_ou(p_requete)) DESC
           ) AS rang
    FROM candidats
    WHERE p_requete IS NOT NULL AND p_requete <> ''
      AND requete_ou(p_requete) IS NOT NULL
      AND fts @@ requete_ou(p_requete)
    LIMIT p_candidats
),
fusion AS (
    SELECT c.id,
           COALESCE(1.0 / (60 + rd.rang), 0) + COALESCE(1.0 / (60 + rl.rang), 0) AS score
    FROM candidats c
    LEFT JOIN rang_dense   rd ON rd.id = c.id
    LEFT JOIN rang_lexical rl ON rl.id = c.id
    WHERE rd.rang IS NOT NULL OR rl.rang IS NOT NULL
)
SELECT c.id, c.titre, c.contenu, c.phase, c.doc_titre, c.organisme,
       c.url_officielle, c.version, ROUND(f.score::numeric, 5)
FROM fusion f
JOIN candidats c ON c.id = f.id
ORDER BY f.score DESC
LIMIT p_limit;
$$ LANGUAGE sql STABLE;
