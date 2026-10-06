-- ============================================================================
-- Suivi du remplacement des fiches RNCP.
--
-- La migration 006 avait prévu ce suivi sur la table `fiche_rncp`, qui n'est
-- pas celle que l'application interroge : le modèle RncpFiche pointe sur
-- `rncp_fiches`, alimentée par l'export quotidien de France Compétences.
-- Le garde-fou décrit en 006 n'a donc jamais protégé personne.
--
-- Ce que ce défaut produisait : un master d'économie et gestion dont
-- l'enregistrement était échu, et dont la fiche remplaçante existait depuis
-- des mois, s'affichait « actif et reconnu par l'État ». La colonne d'état
-- de l'export le déclarait encore actif, et c'est la seule que le verdict
-- consultait.
--
-- Trois corrections vont ensemble, et aucune ne suffit seule :
--   1. ici, la colonne qui porte le remplaçant ;
--   2. dans l'ingestion, l'état absent cesse de valoir « actif » ;
--   3. dans le verdict, l'échéance est comparée à la date du jour.
--
-- Après application : relancer `python -m app.scripts.sync_rncp`. La table
-- est remplacée entièrement à chaque synchronisation, donc la colonne se
-- remplit d'elle-même ; aucune reprise de données n'est nécessaire.
-- ============================================================================

ALTER TABLE rncp_fiches
    ADD COLUMN IF NOT EXISTS remplace_par VARCHAR(20) NOT NULL DEFAULT '';

-- Retrouver les fiches périmées est la requête que l'on posera le plus
-- souvent : une fiche remplacée, ou échue mais encore déclarée active.
CREATE INDEX IF NOT EXISTS idx_rncp_remplace_par
    ON rncp_fiches (remplace_par)
    WHERE remplace_par <> '';

COMMENT ON COLUMN rncp_fiches.remplace_par IS
    'Code de la fiche remplaçante (colonne Nouvelle_Certification de '
    'l''export France Compétences). Vide si la fiche n''est pas remplacée.';
