-- ============================================================================
-- Réconciliation des actions prises hors ligne.
--
-- Le problème
-- -----------
-- Un étudiant coche l'étape 3 dans un taxi, sans réseau. Le lendemain il
-- ouvre One Moov sur l'ordinateur d'un cybercafé, décoche l'étape 3 et coche
-- la 4. Puis son téléphone retrouve du réseau et rejoue sa file d'attente.
-- Sans règle explicite, la dernière requête arrivée gagne, et l'étudiant voit
-- son travail de la veille écraser celui d'aujourd'hui.
--
-- La règle retenue : dernière écriture gagnante, PAR ÉTAPE
-- --------------------------------------------------------
-- Un horodatage par étape, et non un pour toute la feuille de route. Cocher
-- l'étape 4 sur un appareil et l'étape 7 sur un autre conserve les deux :
-- les deux actions portent sur des registres différents, il n'y a pas de
-- conflit à trancher. Seules deux actions sur LA MÊME étape se départagent,
-- et c'est la plus récente qui l'emporte.
--
-- Un tableau d'entiers ne peut pas porter cette information. D'où une colonne
-- JSONB qui associe l'indice de l'étape à la date de sa dernière décision :
--
--     {"3": "2026-09-23T18:40:12Z", "4": "2026-09-24T09:02:00Z"}
--
-- etapes_faites reste la source de vérité de l'affichage. etapes_horodatage
-- ne sert qu'à arbitrer, et garde aussi trace des étapes DÉcochées : sans
-- cela, un décochage n'aurait pas de date et une action plus ancienne
-- pourrait le défaire.
--
-- Ce que cette règle ne résout pas, et qu'il faut savoir
-- -----------------------------------------------------
-- L'horodatage vient de l'appareil de l'étudiant. Une horloge de téléphone
-- déréglée fausse l'arbitrage. Le serveur borne les dates situées dans le
-- futur, ce qui neutralise le cas le plus courant — une horloge en avance qui
-- ferait gagner une action pour toujours. Une horloge en retard, elle, fait
-- simplement perdre les actions de cet appareil : l'étudiant perd son
-- cochage, ce qui est visible et rattrapable, au lieu de perdre le reste.
--
-- Un compteur logique par appareil réglerait le cas proprement. Il n'est pas
-- justifié ici : les deux actions synchronisables sont idempotentes et sans
-- conséquence financière. Un paiement ne passe jamais par ce chemin.
-- ============================================================================

ALTER TABLE roadmap_enregistree
    ADD COLUMN IF NOT EXISTS etapes_horodatage JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Le profil se réconcilie champ par champ, avec une seule date pour tout
-- l'objet. C'est suffisant : la question n'est pas de savoir quel champ est
-- le plus récent, mais lequel des deux profils gagne quand les deux
-- renseignent le même champ. Les champs que l'un connaît et l'autre pas sont
-- conservés dans les deux sens, donc rien n'est jamais détruit.
ALTER TABLE orientation_enregistree
    ADD COLUMN IF NOT EXISTS maj_horodatage TIMESTAMPTZ;

-- Les lignes existantes prennent leur date de mise à jour serveur comme
-- point de départ : une action hors ligne antérieure ne doit pas les écraser.
UPDATE orientation_enregistree
   SET maj_horodatage = maj_le
 WHERE maj_horodatage IS NULL;

-- ----------------------------------------------------------------------------
-- Ce qui n'est PAS créé ici, et c'est délibéré
--
-- Aucune table de messages, aucune colonne de conversation. La file d'attente
-- du client ne connaît que deux types d'action, « etape » et « profil ». Une
-- question écrite hors ligne repart comme un appel d'agent ordinaire et ne
-- traverse jamais ce chemin. Un test parcourt le schéma et échoue si une
-- colonne capable de contenir un échange apparaît.
-- ----------------------------------------------------------------------------
