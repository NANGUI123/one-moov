-- ============================================================================
-- Comptes étudiants.
--
-- Ce fichier change la nature du produit, et il faut le dire franchement :
-- jusqu'ici One Moov ne conservait rien. Avec les comptes, l'application
-- conserve. Le principe devient donc la minimisation et la réversibilité,
-- pas l'absence de stockage.
--
-- Ce qui est conservé, et rien d'autre :
--   - une adresse e-mail, parce qu'il faut bien un identifiant ;
--   - une empreinte de mot de passe, jamais le mot de passe ;
--   - le projet d'études et la feuille de route, qui sont le service rendu.
--
-- Ce qui n'est PAS conservé, délibérément :
--   - aucun nom, aucune adresse postale, aucun document, aucune pièce
--     d'identité, aucune coordonnée bancaire ;
--   - aucune conversation avec les agents. Les échanges restent dans le
--     navigateur. C'est ce qui reste de la promesse initiale, et c'est la
--     partie la plus sensible : un historique de conversation en dit bien
--     plus long sur quelqu'un qu'une liste de champs.
--
-- La suppression est un DELETE sur utilisateur ; tout le reste part en
-- cascade. Pas d'effacement logique, pas de corbeille : le droit à la
-- suppression est un vrai effacement.
-- ============================================================================

CREATE TABLE IF NOT EXISTS utilisateur (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- L'adresse est stockée en minuscules par la contrainte ci-dessous :
    -- deux comptes ne peuvent pas différer par la seule casse.
    email               TEXT NOT NULL UNIQUE CHECK (email = lower(email) AND position('@' in email) > 1),
    -- scrypt : sel et paramètres inclus dans la chaîne. Jamais le mot de passe.
    mot_de_passe        TEXT NOT NULL,
    email_verifie       BOOLEAN NOT NULL DEFAULT FALSE,
    cree_le             TIMESTAMPTZ NOT NULL DEFAULT now(),
    derniere_activite   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_utilisateur_email ON utilisateur (email);

-- --- Vérification de l'adresse ------------------------------------------

-- Le code lui-même n'est pas stocké : seulement son empreinte. Un accès en
-- lecture à la base ne permet donc pas de valider un compte à la place de
-- son propriétaire.
CREATE TABLE IF NOT EXISTS code_verification (
    id              SERIAL PRIMARY KEY,
    utilisateur_id  UUID NOT NULL REFERENCES utilisateur(id) ON DELETE CASCADE,
    code_empreinte  TEXT NOT NULL,
    expire_le       TIMESTAMPTZ NOT NULL,
    utilise_le      TIMESTAMPTZ,
    tentatives      SMALLINT NOT NULL DEFAULT 0,
    cree_le         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_code_utilisateur ON code_verification (utilisateur_id, expire_le DESC);

-- --- Le projet d'études --------------------------------------------------

-- Un seul projet par compte : l'étudiant construit son projet, il ne gère
-- pas un portefeuille de projets. JSONB parce que le profil évolue avec les
-- campagnes, et qu'une colonne par champ imposerait une migration à chaque
-- ajout de question.
CREATE TABLE IF NOT EXISTS orientation_enregistree (
    utilisateur_id  UUID PRIMARY KEY REFERENCES utilisateur(id) ON DELETE CASCADE,
    profil          JSONB NOT NULL,
    maj_le          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- --- La feuille de route -------------------------------------------------

CREATE TABLE IF NOT EXISTS roadmap_enregistree (
    utilisateur_id  UUID PRIMARY KEY REFERENCES utilisateur(id) ON DELETE CASCADE,
    contenu         JSONB NOT NULL,
    etapes_faites   INTEGER[] NOT NULL DEFAULT '{}',
    secteurs_payes  TEXT[] NOT NULL DEFAULT '{}',
    chatbot_ouvert  BOOLEAN NOT NULL DEFAULT FALSE,
    maj_le          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- --- Purge ---------------------------------------------------------------

-- Minimisation dans la durée : un compte jamais vérifié n'a aucune raison
-- de rester. À appeler depuis une tâche planifiée.
CREATE OR REPLACE FUNCTION purger_comptes_non_verifies(p_jours INTEGER DEFAULT 7)
RETURNS INTEGER AS $$
DECLARE
    supprimes INTEGER;
BEGIN
    DELETE FROM utilisateur
     WHERE email_verifie = FALSE
       AND cree_le < now() - make_interval(days => p_jours);
    GET DIAGNOSTICS supprimes = ROW_COUNT;
    RETURN supprimes;
END;
$$ LANGUAGE plpgsql;
