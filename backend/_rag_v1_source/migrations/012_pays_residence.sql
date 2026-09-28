-- Pays de résidence du compte : utilisé pour adapter la procédure Campus France
-- et les opérateurs Mobile Money disponibles pour les paiements One Moov.
ALTER TABLE utilisateur ADD COLUMN IF NOT EXISTS pays_residence TEXT;

DO $$ BEGIN
    ALTER TYPE objet_paiement ADD VALUE IF NOT EXISTS 'correction_orientation';
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS idx_utilisateur_pays_residence
    ON utilisateur (pays_residence);
