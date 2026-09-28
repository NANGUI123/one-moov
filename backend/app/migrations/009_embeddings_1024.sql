-- ============================================================================
-- Alignement des bases existantes sur des vecteurs à 1024 dimensions.
--
-- Pourquoi ce changement : un modèle d'embeddings multilingue local ne tient
-- pas dans les 512 Mo du plan d'hébergement. Sa table de vocabulaire occupe
-- à elle seule ~384 Mo de RAM, avec un pic au double au chargement. On passe
-- donc à une API, et mistral-embed produit 1024 dimensions.
--
-- Sur une base NEUVE, ce fichier n'a rien à faire : 001 et 003 créent déjà
-- les colonnes en 1024. Il n'agit que sur une base déjà migrée en 384.
--
-- CE QU'IL FAUT SAVOIR
--
-- Les vecteurs de deux modèles différents vivent dans des espaces sans
-- rapport. Mélanger d'anciens et de nouveaux vecteurs dans la même colonne
-- ne produit PAS d'erreur : la recherche renvoie du bruit, en silence.
-- C'est le pire des échecs, parce qu'il ne se voit pas.
--
-- Ce fichier vide donc les vecteurs plutôt que de tenter une conversion. Le
-- corpus doit être ré-embeddé en entier ensuite :
--
--     python -m scripts.reembedder
--
-- Entre les deux, la recherche fonctionne en plein texte français seul.
-- C'est dégradé, pas cassé.
-- ============================================================================

DO $$
DECLARE
    dimension_actuelle INTEGER;
BEGIN
    -- atttypmod porte la dimension déclarée d'une colonne pgvector.
    SELECT a.atttypmod INTO dimension_actuelle
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
     WHERE c.relname = 'passage' AND a.attname = 'embedding' AND a.attnum > 0;

    IF dimension_actuelle IS NOT NULL AND dimension_actuelle <> 1024 THEN
        RAISE NOTICE 'Vecteurs en % dimensions : passage à 1024, corpus à ré-embedder.',
                     dimension_actuelle;

        DROP INDEX IF EXISTS idx_etab_embedding;
        DROP INDEX IF EXISTS idx_passage_embedding;

        -- On ne touche PAS aux fonctions de recherche.
        --
        -- En PostgreSQL, le modificateur de type ne fait pas partie de la
        -- signature : vector(384) et vector(1024) sont la même signature
        -- « vector ». Il n'y a donc jamais deux surcharges à départager, et
        -- le CREATE OR REPLACE de 001 et 003 a déjà remplacé le corps.
        -- Un DROP FUNCTION ici supprimerait la bonne fonction, pas
        -- l'ancienne — et la recherche tomberait avec « function does not
        -- exist ».

        ALTER TABLE etablissement DROP COLUMN embedding;
        ALTER TABLE etablissement ADD COLUMN embedding vector(1024);

        ALTER TABLE passage DROP COLUMN embedding;
        ALTER TABLE passage ADD COLUMN embedding vector(1024);
    END IF;
END $$;

-- Avec quel modèle chaque vecteur a été produit. Sans cette colonne, on ne
-- peut plus savoir ce qui est à jour après un changement de fournisseur.
ALTER TABLE etablissement ADD COLUMN IF NOT EXISTS modele_embedding TEXT;
ALTER TABLE passage        ADD COLUMN IF NOT EXISTS modele_embedding TEXT;

-- Les index HNSW sont recréés ici pour une base neuve, et par le script de
-- ré-embedding après un remplissage massif — un index construit sur des
-- vecteurs absents ne sert à rien.
CREATE INDEX IF NOT EXISTS idx_etab_embedding
    ON etablissement USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_passage_embedding
    ON passage USING hnsw (embedding vector_cosine_ops);
