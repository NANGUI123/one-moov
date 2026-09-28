-- ============================================================================
-- Paiements et notifications.
--
-- Deux principes gouvernent ces tables, et ils viennent l'un comme l'autre
-- de la façon dont les paiements échouent réellement en Afrique centrale.
--
-- 1. LE WEBHOOK N'EST PAS LA VÉRITÉ.
--    N'importe qui connaissant l'URL de notification peut poster un faux
--    « paiement confirmé ». Le webhook ne sert qu'à déclencher une
--    re-interrogation de l'API de statut du fournisseur ; seul le résultat
--    de cette seconde requête est écrit ici. La colonne statut ne doit
--    jamais être renseignée depuis le corps d'un webhook.
--
-- 2. UN PAIEMENT RÉUSSI DONT LE WEBHOOK N'ARRIVE JAMAIS EST LE CAS NORMAL,
--    pas le cas rare : réseau instable, serveur en redéploiement, timeout.
--    D'où la colonne prochaine_verification, qu'un job de réconciliation
--    balaie régulièrement. Sans ce filet, un étudiant paie et n'obtient
--    rien — le pire échec possible pour ce produit.
-- ============================================================================

DO $$ BEGIN
    CREATE TYPE statut_paiement AS ENUM (
        'en_attente',   -- créé, l'étudiant n'a pas encore validé sur son téléphone
        'en_cours',     -- le fournisseur traite
        'reussi',       -- confirmé par l'API de statut du fournisseur
        'echoue',       -- refusé, solde insuffisant, expiré
        'abandonne'     -- jamais confirmé, clos par la réconciliation
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE objet_paiement AS ENUM (
        'roadmap_public', 'roadmap_prive', 'roadmap_deux',
        'chatbot', 'debloquer_prive'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS paiement (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    utilisateur_id         UUID REFERENCES utilisateur(id) ON DELETE SET NULL,

    objet                  objet_paiement NOT NULL,
    montant_fcfa           INTEGER NOT NULL CHECK (montant_fcfa >= 100),
    pays                   TEXT NOT NULL,
    operateur              TEXT NOT NULL,      -- mtn | orange | airtel
    -- Conservé le temps de la transaction seulement : la réconciliation
    -- l'efface une fois le paiement clos. Voir purger_numeros_paiement().
    telephone              TEXT,

    fournisseur            TEXT NOT NULL,      -- pawapay | manuel | mock
    -- Référence côté fournisseur. L'unicité est ce qui rend le traitement
    -- idempotent : un webhook livré deux fois ne crée pas deux paiements.
    reference_fournisseur  TEXT,

    statut                 statut_paiement NOT NULL DEFAULT 'en_attente',
    motif_echec            TEXT,

    -- Réconciliation : quand re-interroger le fournisseur, et combien de
    -- fois on l'a déjà fait.
    prochaine_verification TIMESTAMPTZ,
    verifications          SMALLINT NOT NULL DEFAULT 0,

    cree_le                TIMESTAMPTZ NOT NULL DEFAULT now(),
    clos_le                TIMESTAMPTZ,

    CONSTRAINT reference_unique_par_fournisseur
        UNIQUE (fournisseur, reference_fournisseur)
);

CREATE INDEX IF NOT EXISTS idx_paiement_utilisateur ON paiement (utilisateur_id);
CREATE INDEX IF NOT EXISTS idx_paiement_a_verifier
    ON paiement (prochaine_verification)
    WHERE statut IN ('en_attente', 'en_cours');

-- Le numéro de téléphone n'a d'utilité que pendant la transaction. Une fois
-- le paiement clos depuis un moment, il n'y a plus de raison de le garder.
CREATE OR REPLACE FUNCTION purger_numeros_paiement(p_jours INTEGER DEFAULT 30)
RETURNS INTEGER AS $$
DECLARE
    touches INTEGER;
BEGIN
    UPDATE paiement SET telephone = NULL
     WHERE telephone IS NOT NULL
       AND clos_le IS NOT NULL
       AND clos_le < now() - make_interval(days => p_jours);
    GET DIAGNOSTICS touches = ROW_COUNT;
    RETURN touches;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Notifications
--
-- Les rappels d'échéance sont par nature envoyés hors de la fenêtre de 24 h
-- de WhatsApp : ils exigent donc un template approuvé par Meta. Le nom du
-- template et ses paramètres sont stockés ici, pas construits à la volée,
-- pour qu'un template rejeté ou renommé se corrige en base.
-- ============================================================================

DO $$ BEGIN
    CREATE TYPE canal_notification AS ENUM ('whatsapp', 'email');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE statut_notification AS ENUM (
        'planifiee', 'envoyee', 'echouee', 'annulee'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Le consentement au canal, et le numéro. Séparé de la table utilisateur
-- parce que c'est une donnée que l'étudiant donne explicitement, qu'il peut
-- retirer seul, et qui n'a pas la même durée de vie que son compte.
CREATE TABLE IF NOT EXISTS abonnement_notification (
    utilisateur_id   UUID PRIMARY KEY REFERENCES utilisateur(id) ON DELETE CASCADE,
    whatsapp_actif   BOOLEAN NOT NULL DEFAULT FALSE,
    -- Format international, sans espaces : +237…, +242…
    telephone        TEXT CHECK (telephone IS NULL OR telephone ~ '^\+[0-9]{8,15}$'),
    email_actif      BOOLEAN NOT NULL DEFAULT TRUE,
    consenti_le      TIMESTAMPTZ,
    maj_le           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notification (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    utilisateur_id    UUID NOT NULL REFERENCES utilisateur(id) ON DELETE CASCADE,
    canal             canal_notification NOT NULL,

    -- Nom du template approuvé côté Meta, et ses paramètres positionnels.
    -- Pour l'e-mail, le template sert de clé de rendu.
    modele            TEXT NOT NULL,
    parametres        JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Ce à quoi le rappel se rattache : l'étape de la feuille de route.
    etape_ordre       SMALLINT,
    echeance          DATE,

    planifiee_pour    TIMESTAMPTZ NOT NULL,
    statut            statut_notification NOT NULL DEFAULT 'planifiee',
    envoyee_le        TIMESTAMPTZ,
    motif_echec       TEXT,
    tentatives        SMALLINT NOT NULL DEFAULT 0,

    cree_le           TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- On ne renvoie pas deux fois le même rappel pour la même étape.
    CONSTRAINT rappel_unique
        UNIQUE (utilisateur_id, canal, modele, etape_ordre)
);

CREATE INDEX IF NOT EXISTS idx_notification_a_envoyer
    ON notification (planifiee_pour)
    WHERE statut = 'planifiee';

-- Plafond de sécurité : Meta limite à 250 destinataires uniques par 24 h
-- tant que l'entreprise n'est pas vérifiée. Dépasser dégrade la qualité du
-- numéro et peut le faire restreindre. Cette vue permet au planificateur de
-- s'arrêter avant.
CREATE OR REPLACE VIEW envois_whatsapp_24h AS
SELECT count(DISTINCT utilisateur_id) AS destinataires
  FROM notification
 WHERE canal = 'whatsapp'
   AND statut = 'envoyee'
   AND envoyee_le > now() - interval '24 hours';
