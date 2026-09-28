-- ============================================================================
-- RAG V1 : métadonnées de chunking et traçabilité des embeddings.
--
-- Un passage devient le chunk réellement indexé. Ces colonnes permettent de
-- contrôler sa taille, de détecter une modification et de savoir quel modèle
-- a produit son vecteur.
-- ============================================================================

ALTER TABLE passage
    ADD COLUMN IF NOT EXISTS token_count INTEGER;

ALTER TABLE passage
    ADD COLUMN IF NOT EXISTS char_count INTEGER;

ALTER TABLE passage
    ADD COLUMN IF NOT EXISTS contenu_hash TEXT;

ALTER TABLE passage
    ADD COLUMN IF NOT EXISTS modele_embedding TEXT;

CREATE INDEX IF NOT EXISTS idx_passage_contenu_hash
    ON passage (contenu_hash);

CREATE INDEX IF NOT EXISTS idx_passage_modele_embedding
    ON passage (modele_embedding);

-- Remplit les métadonnées des anciennes lignes sans toucher à leur contenu.
UPDATE passage
SET
    char_count = COALESCE(char_count, length(contenu)),
    token_count = COALESCE(token_count, GREATEST(1, round(length(contenu) / 4.0))::integer),
    contenu_hash = COALESCE(
        contenu_hash,
        substr(md5(contenu), 1, 32)
    )
WHERE char_count IS NULL
   OR token_count IS NULL
   OR contenu_hash IS NULL;
