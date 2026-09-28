-- ============================================================================
-- Faits critiques.
--
-- C'est la réponse au problème des informations qui changent : frais, seuils
-- de ressources, quotas d'heures, dates de campagne. Ces valeurs ne viennent
-- JAMAIS du modèle de langage. Elles sont saisies, sourcées, datées, et
-- versionnées.
--
-- Chaque fait porte :
--   - sa valeur et son unité
--   - l'URL officielle d'où elle vient
--   - la date de dernière vérification
--   - une période de validité (une campagne Campus France, par exemple)
--
-- Quand un fait est mis à jour, l'ancien n'est pas écrasé : il est clos par
-- une date de fin. On garde ainsi l'historique, et on peut expliquer sur
-- quelle valeur une feuille de route a été construite.
-- ============================================================================

DO $$ BEGIN
    CREATE TYPE categorie_fait AS ENUM (
        'frais', 'seuil_ressources', 'quota_heures', 'date_campagne', 'delai', 'autre'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS fait_critique (
    id              SERIAL PRIMARY KEY,
    cle             TEXT NOT NULL,              -- ex : 'frais_dossier_cf_congo'
    categorie       categorie_fait NOT NULL,
    libelle         TEXT NOT NULL,              -- formulation lisible par l'étudiant
    valeur          TEXT NOT NULL,              -- en texte : gère montants, dates, durées
    unite           TEXT,                       -- '€', 'FCFA', 'heures/an', NULL
    pays            TEXT,                       -- 'Cameroun', 'Congo-Brazzaville', NULL = tous
    source_url      TEXT NOT NULL,
    source_libelle  TEXT NOT NULL,

    verifie_le      DATE NOT NULL,
    valide_du       DATE NOT NULL DEFAULT CURRENT_DATE,
    valide_au       DATE,                       -- NULL = toujours en vigueur
    remplace_id     INTEGER REFERENCES fait_critique(id),

    cree_le         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fait_cle    ON fait_critique (cle);
CREATE INDEX IF NOT EXISTS idx_fait_actif  ON fait_critique (cle, valide_au) WHERE valide_au IS NULL;
CREATE INDEX IF NOT EXISTS idx_fait_pays   ON fait_critique (pays);

-- Une seule valeur en vigueur par clé et par pays.
CREATE UNIQUE INDEX IF NOT EXISTS idx_fait_unique_actif
    ON fait_critique (cle, COALESCE(pays, ''))
    WHERE valide_au IS NULL;

-- --- Vue des faits en vigueur ------------------------------------------

CREATE OR REPLACE VIEW fait_en_vigueur AS
SELECT id, cle, categorie, libelle, valeur, unite, pays,
       source_url, source_libelle, verifie_le, valide_du,
       (CURRENT_DATE - verifie_le) AS jours_depuis_verification,
       -- Au-delà de 90 jours sans contrôle, le fait est signalé comme
       -- potentiellement périmé. L'interface l'affiche différemment.
       ((CURRENT_DATE - verifie_le) > 90) AS a_reverifier
FROM fait_critique
WHERE valide_au IS NULL;

-- --- Clore un fait et le remplacer --------------------------------------
-- Usage : SELECT remplacer_fait('frais_dossier_cf_congo', '80000', ...);

CREATE OR REPLACE FUNCTION remplacer_fait(
    p_cle            TEXT,
    p_nouvelle_valeur TEXT,
    p_source_url     TEXT,
    p_source_libelle TEXT,
    p_pays           TEXT DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    ancien   fait_critique%ROWTYPE;
    nouvel_id INTEGER;
BEGIN
    SELECT * INTO ancien
    FROM fait_critique
    WHERE cle = p_cle
      AND COALESCE(pays, '') = COALESCE(p_pays, '')
      AND valide_au IS NULL;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Aucun fait en vigueur pour la clé % (pays %)', p_cle, p_pays;
    END IF;

    UPDATE fait_critique SET valide_au = CURRENT_DATE WHERE id = ancien.id;

    INSERT INTO fait_critique (cle, categorie, libelle, valeur, unite, pays,
                               source_url, source_libelle, verifie_le, valide_du, remplace_id)
    VALUES (ancien.cle, ancien.categorie, ancien.libelle, p_nouvelle_valeur, ancien.unite,
            ancien.pays, p_source_url, p_source_libelle, CURRENT_DATE, CURRENT_DATE, ancien.id)
    RETURNING id INTO nouvel_id;

    RETURN nouvel_id;
END;
$$ LANGUAGE plpgsql;

-- --- Journal de surveillance des sources --------------------------------
-- Alimenté par le script de veille. Il ne récupère pas le contenu : il
-- signale seulement qu'une page officielle a changé depuis le dernier
-- passage, pour qu'un humain aille vérifier le fait concerné.

CREATE TABLE IF NOT EXISTS surveillance_source (
    id           SERIAL PRIMARY KEY,
    url          TEXT NOT NULL UNIQUE,
    libelle      TEXT NOT NULL,
    cles_liees   TEXT[] NOT NULL DEFAULT '{}',   -- faits à revoir si la page bouge
    empreinte    TEXT,                            -- hachage du contenu
    verifie_le   TIMESTAMPTZ,
    change_le    TIMESTAMPTZ,
    statut       TEXT NOT NULL DEFAULT 'inconnu'  -- inchange | change | erreur
);
