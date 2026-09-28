-- ============================================================================
-- Données d'amorçage.
--
-- ATTENTION, à lire avant toute mise en production.
-- Les faits critiques ci-dessous proviennent de la spécification du projet
-- et doivent être reconfirmés sur les sources officielles avant d'être
-- présentés à de vrais étudiants. La date de vérification est volontairement
-- ancienne sur certains, afin que l'interface affiche le signalement
-- « à revérifier » et que le mécanisme soit visible.
--
-- Pour mettre un fait à jour :
--   SELECT remplacer_fait('quota_heures_travail', '964',
--                         'https://...', 'Service-Public', NULL);
-- ============================================================================

-- --- Villes ------------------------------------------------------------

INSERT INTO ville (nom, region, cout_vie_mensuel, loyer_moyen_studio, population_etudiante, reseau_diaspora, description) VALUES
 ('Lille',    'Hauts-de-France',      620, 480, 120000, TRUE,  'Grande ville étudiante du nord, coût de la vie contenu, forte présence de la diaspora africaine.'),
 ('Lyon',     'Auvergne-Rhône-Alpes', 700, 560, 160000, TRUE,  'Deuxième pôle universitaire français, large offre de formations, bon réseau de transports.'),
 ('Toulouse', 'Occitanie',            650, 520, 130000, FALSE, 'Pôle aéronautique et scientifique, logement plus abordable qu''en Île-de-France.'),
 ('Nantes',   'Pays de la Loire',     660, 530,  90000, FALSE, 'Ville dynamique de l''ouest, bonne qualité de vie étudiante.'),
 ('Montpellier','Occitanie',          640, 510, 100000, FALSE, 'Forte population étudiante, climat agréable, université pluridisciplinaire.'),
 ('Poitiers', 'Nouvelle-Aquitaine',   560, 420,  28000, FALSE, 'Ville universitaire à taille humaine, parmi les coûts de vie les plus bas.')
ON CONFLICT (nom) DO NOTHING;

-- --- Domaines ----------------------------------------------------------

INSERT INTO domaine (code, libelle) VALUES
 ('INFO',    'Informatique'),
 ('INFO_IA', 'Intelligence artificielle'),
 ('DATA',    'Données et statistiques'),
 ('GESTION', 'Commerce et gestion'),
 ('DROIT',   'Droit'),
 ('INGE',    'Ingénierie'),
 ('SANTE',   'Santé')
ON CONFLICT (code) DO NOTHING;

-- --- Établissements ----------------------------------------------------

INSERT INTO etablissement
 (id, nom, type, secteur, ville_id, niveaux_acceptes, formations_acceptees, langue,
  frais_scolarite_an, niveau_fr_requis, connecte_cf, description, site_web, source, verifie_le)
VALUES
 ('univ_lille_info', 'Université de Lille, master informatique', 'universite', 'public',
  (SELECT id FROM ville WHERE nom='Lille'),
  ARRAY['master','doctorat']::niveau_diplome[], ARRAY['initiale','alternance']::type_formation[], 'francais',
  400, 'B2', TRUE,
  'Master d''informatique avec parcours intelligence artificielle, données massives et génie logiciel. Laboratoire de recherche associé.',
  'https://www.univ-lille.fr', 'site de l''université', CURRENT_DATE - 20),

 ('insa_lyon', 'INSA Lyon', 'ecole_ingenieur', 'public',
  (SELECT id FROM ville WHERE nom='Lyon'),
  ARRAY['master','doctorat']::niveau_diplome[], ARRAY['initiale','alternance']::type_formation[], 'francais',
  2500, 'B2', TRUE,
  'École d''ingénieurs publique, spécialités informatique, génie civil, mécanique et biosciences. Forte ouverture internationale.',
  'https://www.insa-lyon.fr', 'site de l''école', CURRENT_DATE - 20),

 ('univ_toulouse3', 'Université Toulouse III Paul Sabatier', 'universite', 'public',
  (SELECT id FROM ville WHERE nom='Toulouse'),
  ARRAY['licence','master','doctorat']::niveau_diplome[], ARRAY['initiale']::type_formation[], 'francais',
  400, 'B2', TRUE,
  'Université scientifique et de santé, offre large en informatique, mathématiques appliquées et ingénierie.',
  'https://www.univ-tlse3.fr', 'site de l''université', CURRENT_DATE - 20),

 ('univ_poitiers', 'Université de Poitiers', 'universite', 'public',
  (SELECT id FROM ville WHERE nom='Poitiers'),
  ARRAY['licence','master']::niveau_diplome[], ARRAY['initiale','continue']::type_formation[], 'francais',
  400, 'B2', TRUE,
  'Université pluridisciplinaire réputée pour son accueil des étudiants internationaux. Droit, sciences et lettres.',
  'https://www.univ-poitiers.fr', 'site de l''université', CURRENT_DATE - 20),

 ('univ_nantes_gestion', 'Nantes Université, IAE', 'universite', 'public',
  (SELECT id FROM ville WHERE nom='Nantes'),
  ARRAY['master']::niveau_diplome[], ARRAY['initiale','alternance']::type_formation[], 'francais',
  400, 'B2', TRUE,
  'Institut d''administration des entreprises, masters en management, finance et contrôle de gestion.',
  'https://iae.univ-nantes.fr', 'site de l''établissement', CURRENT_DATE - 20),

 ('epita', 'EPITA', 'ecole_ingenieur', 'prive',
  (SELECT id FROM ville WHERE nom='Lyon'),
  ARRAY['master']::niveau_diplome[], ARRAY['initiale','alternance']::type_formation[], 'francais',
  9500, 'B2', TRUE,
  'École d''ingénieurs en informatique, spécialisations intelligence artificielle, cybersécurité et science des données.',
  'https://www.epita.fr', 'site de l''école', CURRENT_DATE - 20),

 ('epitech', 'EPITECH', 'ecole_ingenieur', 'prive',
  (SELECT id FROM ville WHERE nom='Lille'),
  ARRAY['licence','master']::niveau_diplome[], ARRAY['initiale','alternance']::type_formation[], 'francais',
  8900, 'B1', TRUE,
  'École de l''informatique et de l''innovation, pédagogie par projets, développement logiciel et intelligence artificielle.',
  'https://www.epitech.eu', 'site de l''école', CURRENT_DATE - 20),

 ('tbs_toulouse', 'Toulouse Business School', 'ecole_commerce', 'prive',
  (SELECT id FROM ville WHERE nom='Toulouse'),
  ARRAY['master']::niveau_diplome[], ARRAY['initiale','alternance']::type_formation[], 'bilingue',
  15000, 'B1', TRUE,
  'Programme grande école en management, avec parcours analyse de données pour le business et entrepreneuriat.',
  'https://www.tbs-education.fr', 'site de l''école', CURRENT_DATE - 20),

 ('esiea_lille', 'ESIEA', 'ecole_ingenieur', 'prive',
  (SELECT id FROM ville WHERE nom='Lille'),
  ARRAY['master']::niveau_diplome[], ARRAY['initiale']::type_formation[], 'francais',
  8200, 'B2', TRUE,
  'École d''ingénieurs du numérique, intelligence artificielle, systèmes embarqués et cybersécurité.',
  'https://www.esiea.fr', 'site de l''école', CURRENT_DATE - 20),

 ('montpellier_droit', 'Université de Montpellier, faculté de droit', 'universite', 'public',
  (SELECT id FROM ville WHERE nom='Montpellier'),
  ARRAY['licence','master']::niveau_diplome[], ARRAY['initiale']::type_formation[], 'francais',
  400, 'C1', TRUE,
  'Faculté de droit et science politique, masters en droit des affaires et droit international.',
  'https://www.umontpellier.fr', 'site de l''université', CURRENT_DATE - 20)
ON CONFLICT (id) DO NOTHING;

-- Rattachement aux domaines
INSERT INTO etablissement_domaine (etablissement_id, domaine_id)
SELECT e.id, d.id FROM etablissement e, domaine d
WHERE (e.id IN ('univ_lille_info','insa_lyon','univ_toulouse3','epita','epitech','esiea_lille') AND d.code IN ('INFO','INFO_IA','DATA'))
   OR (e.id IN ('tbs_toulouse','univ_nantes_gestion') AND d.code = 'GESTION')
   OR (e.id IN ('montpellier_droit','univ_poitiers') AND d.code = 'DROIT')
   OR (e.id IN ('insa_lyon','esiea_lille') AND d.code = 'INGE')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- Faits critiques.
-- Valeurs issues de la spécification du projet, À RECONFIRMER officiellement.
-- ============================================================================

INSERT INTO fait_critique
 (cle, categorie, libelle, valeur, unite, pays, source_url, source_libelle, verifie_le)
VALUES
 ('quota_heures_travail', 'quota_heures',
  'Nombre d''heures de travail autorisées par an pour un étudiant étranger',
  '964', 'heures par an', NULL,
  'https://www.service-public.fr/particuliers/vosdroits/F2864',
  'Service-Public, travail des étudiants étrangers', CURRENT_DATE - 30),

 ('seuil_ressources_visa', 'seuil_ressources',
  'Ressources mensuelles à justifier pour la demande de visa étudiant',
  '877,50', 'euros par mois', NULL,
  'https://france-visas.gouv.fr',
  'France-Visas, justificatifs de ressources', CURRENT_DATE - 45),

 ('montant_bloque_sans_logement', 'seuil_ressources',
  'Somme à bloquer sur un compte si aucun logement n''est confirmé en France',
  '7 000 000', 'FCFA', 'Congo-Brazzaville',
  'https://www.campusfrance.org/fr/congo',
  'Campus France Congo', CURRENT_DATE - 110),

 ('montant_bloque_avec_logement', 'seuil_ressources',
  'Somme à bloquer si un logement est confirmé en France, avec caution déposée',
  '3 500 000', 'FCFA', 'Congo-Brazzaville',
  'https://www.campusfrance.org/fr/congo',
  'Campus France Congo', CURRENT_DATE - 110),

 ('frais_dossier_campus_france', 'frais',
  'Frais de dossier Campus France à régler avant la validation du dossier',
  '75 000', 'FCFA', 'Congo-Brazzaville',
  'https://www.campusfrance.org/fr/congo',
  'Campus France Congo', CURRENT_DATE - 110),

 ('delai_validation_vlsts', 'delai',
  'Délai pour valider le visa VLS-TS après l''arrivée en France',
  '3', 'mois', NULL,
  'https://administration-etrangers-en-france.interieur.gouv.fr',
  'Ministère de l''Intérieur, validation du VLS-TS', CURRENT_DATE - 30)
ON CONFLICT DO NOTHING;

-- --- Sources à surveiller ----------------------------------------------

INSERT INTO surveillance_source (url, libelle, cles_liees) VALUES
 ('https://www.campusfrance.org/fr/congo', 'Campus France Congo-Brazzaville',
  ARRAY['montant_bloque_sans_logement','montant_bloque_avec_logement','frais_dossier_campus_france']),
 ('https://www.campusfrance.org/fr/cameroun', 'Campus France Cameroun', ARRAY['frais_dossier_campus_france']),
 ('https://france-visas.gouv.fr', 'France-Visas', ARRAY['seuil_ressources_visa']),
 ('https://www.service-public.fr/particuliers/vosdroits/F2864', 'Service-Public, travail étudiant', ARRAY['quota_heures_travail'])
ON CONFLICT (url) DO NOTHING;
