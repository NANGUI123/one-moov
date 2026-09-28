-- ============================================================================
-- Fiches RNCP (France Compétences).
--
-- Une fiche RNCP dit qu'une certification est reconnue par l'État, à quel
-- niveau, par qui, et jusqu'à quand. C'est exactement le genre d'information
-- qu'un modèle de langage ne doit jamais produire : un code inventé a la même
-- allure qu'un vrai, et un étudiant n'a aucun moyen de faire la différence.
--
-- Donc : table, source, date de vérification, lookup déterministe. L'IA ne
-- touche jamais à ces valeurs, elle peut seulement les commenter.
--
-- Trois pièges qui ont dicté ce schéma, constatés sur les fiches réelles :
--
--   1. Le champ « État » ne suffit pas. Des fiches restent affichées actives
--      alors que leur date d'échéance est passée et qu'une fiche
--      remplaçante existe. On croise donc état, échéance et remplacement.
--
--   2. Les fiches se remplacent en chaîne (EPITECH : 17286 → 37985 → 42505).
--      On garde le lien de remplacement pour pouvoir suivre la chaîne au
--      moment de l'affichage plutôt que de figer un code périmé.
--
--   3. Pour un diplôme universitaire, une seule « fiche nationale » couvre
--      des dizaines d'universités. Dire « cette formation est enregistrée
--      sous RNCP38186 » est exact, mais ne prouve rien sur l'établissement.
--      Le lien établissement ↔ fiche passe par la liste des certificateurs,
--      d'où la colonne certificateur_verifie et le champ portee.
-- ============================================================================

DO $$ BEGIN
    CREATE TYPE etat_fiche AS ENUM ('active','expiree','remplacee','inconnue');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    -- « nationale » : fiche partagée par plusieurs établissements.
    -- « etablissement » : fiche propre à un établissement (titre d'ingénieur, etc.)
    CREATE TYPE portee_fiche AS ENUM ('nationale','etablissement');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS fiche_rncp (
    code                  TEXT PRIMARY KEY,          -- « RNCP40531 »
    numero                INTEGER NOT NULL,          -- 40531, pour construire l'URL
    intitule              TEXT NOT NULL,
    niveau_europeen       SMALLINT,                  -- 6 = licence, 7 = master
    portee                portee_fiche NOT NULL DEFAULT 'nationale',
    certificateur         TEXT,
    certificateur_siret   TEXT,                      -- plus stable que le nom
    etat                  etat_fiche NOT NULL DEFAULT 'inconnue',
    echeance              DATE,
    remplace_par          TEXT REFERENCES fiche_rncp(code),

    source_url            TEXT NOT NULL,
    verifie_le            DATE NOT NULL DEFAULT CURRENT_DATE,

    fts tsvector GENERATED ALWAYS AS (to_tsvector('french', coalesce(intitule,''))) STORED
);

CREATE INDEX IF NOT EXISTS idx_rncp_fts    ON fiche_rncp USING GIN (fts);
CREATE INDEX IF NOT EXISTS idx_rncp_numero ON fiche_rncp (numero);

-- --- Rattachement établissement ↔ fiche ---------------------------------

CREATE TABLE IF NOT EXISTS etablissement_rncp (
    etablissement_id      TEXT NOT NULL REFERENCES etablissement(id) ON DELETE CASCADE,
    code_rncp             TEXT NOT NULL REFERENCES fiche_rncp(code),
    niveau                niveau_diplome NOT NULL,
    -- Faux tant que la présence de l'établissement dans la liste des
    -- certificateurs n'a pas été constatée. L'interface le dit franchement
    -- plutôt que de laisser croire à un agrément.
    certificateur_verifie BOOLEAN NOT NULL DEFAULT FALSE,
    note                  TEXT,
    verifie_le            DATE NOT NULL DEFAULT CURRENT_DATE,
    PRIMARY KEY (etablissement_id, code_rncp)
);

-- --- Vue : l'état réel, échéance comprise --------------------------------

-- On recalcule l'état plutôt que de faire confiance à la colonne : une fiche
-- dont l'échéance est passée est expirée, quoi qu'en dise le répertoire.
CREATE OR REPLACE VIEW fiche_rncp_reelle AS
SELECT
    f.*,
    CASE
        WHEN f.remplace_par IS NOT NULL                     THEN 'remplacee'
        WHEN f.echeance IS NOT NULL AND f.echeance < CURRENT_DATE THEN 'expiree'
        ELSE f.etat::TEXT
    END                                          AS etat_reel,
    (f.echeance IS NOT NULL AND f.echeance < CURRENT_DATE) AS echue,
    (f.echeance - CURRENT_DATE)                  AS jours_avant_echeance,
    (CURRENT_DATE - f.verifie_le)                AS jours_depuis_verification,
    ((CURRENT_DATE - f.verifie_le) > 30)         AS a_reverifier
FROM fiche_rncp f;

-- --- Lookup déterministe -------------------------------------------------

-- Suit la chaîne de remplacement jusqu'à la fiche en vigueur. Bornée, pour
-- qu'une boucle de données ne fasse pas tourner la requête indéfiniment.
CREATE OR REPLACE FUNCTION fiche_en_vigueur(p_code TEXT)
RETURNS TEXT AS $$
DECLARE
    courant TEXT := p_code;
    suivant TEXT;
    garde   INTEGER := 0;
BEGIN
    LOOP
        SELECT remplace_par INTO suivant FROM fiche_rncp WHERE code = courant;
        EXIT WHEN suivant IS NULL OR garde > 10;
        courant := suivant;
        garde := garde + 1;
    END LOOP;
    RETURN courant;
END;
$$ LANGUAGE plpgsql STABLE;
