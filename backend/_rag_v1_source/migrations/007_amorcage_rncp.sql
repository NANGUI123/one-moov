-- ============================================================================
-- Amorçage des fiches RNCP.
--
-- PROVENANCE : ces codes ont été relevés un par un sur francecompetences.fr
-- le 23 septembre 2026. Ils sont réels. Aucun n'a été deviné, et les
-- formations pour lesquelles aucune fiche fiable n'a été trouvée sont
-- absentes de ce fichier — c'est volontaire, et c'est préférable à un
-- rattachement approximatif.
--
-- AVANT MISE EN PRODUCTION : relancer `python -m scripts.ingerer_rncp`, qui
-- récupère le jeu de données ouvert quotidien de France Compétences et
-- réactualise état, échéance et remplacement. Les valeurs ci-dessous sont
-- un point de départ, pas une vérité durable : une fiche est déjà expirée
-- dans ce fichier (voir RNCP37985), ce qui illustre exactement le problème.
-- ============================================================================

INSERT INTO fiche_rncp
    (code, numero, intitule, niveau_europeen, portee, certificateur,
     certificateur_siret, etat, echeance, source_url, verifie_le)
VALUES
    ('RNCP40531', 40531,
     'Titre ingénieur - Ingénieur diplômé de l''École pour l''informatique et les techniques avancées',
     7, 'etablissement', 'EPITA', '89819207500015', 'active', '2028-08-31',
     'https://www.francecompetences.fr/recherche/rncp/40531/', '2026-09-23'),

    ('RNCP42505', 42505, 'Expert en ingénierie logicielle',
     7, 'etablissement', 'EPITECH', '42385519600014', 'active', '2031-06-26',
     'https://www.francecompetences.fr/recherche/rncp/42505/', '2026-09-23'),

    -- Fiche EPITECH précédente, expirée le 20 septembre 2026. Conservée pour
    -- que la chaîne de remplacement soit lisible, et parce qu'elle est la
    -- meilleure démonstration du problème : trois jours avant la date de
    -- relevé, ce code aurait été affiché comme valide.
    ('RNCP37985', 37985, 'Expert en technologies de l''information',
     7, 'etablissement', 'EPITECH', '42385519600014', 'expiree', '2026-09-20',
     'https://www.francecompetences.fr/recherche/rncp/37985/', '2026-09-23'),

    ('RNCP39893', 39893,
     'Titre ingénieur - Ingénieur diplômé de l''École supérieure d''informatique, électronique, automatique',
     7, 'etablissement', 'ESIEA', '31134913800017', 'active', '2029-08-31',
     'https://www.francecompetences.fr/recherche/rncp/39893/', '2026-09-23'),

    ('RNCP42247', 42247,
     'Titre ingénieur - Ingénieur diplômé de l''Institut national des sciences appliquées de Lyon, spécialité informatique',
     7, 'etablissement', 'INSA Lyon', '19690192000013', 'active', '2031-08-31',
     'https://www.francecompetences.fr/recherche/rncp/42247/', '2026-09-23'),

    ('RNCP36421', 36421, 'DipViGrM - Programme Grande École de TBS Education',
     7, 'etablissement', 'Toulouse Business School', '81751739400018', 'active', '2027-08-31',
     'https://www.francecompetences.fr/recherche/rncp/36421/', '2026-09-23'),

    ('RNCP38186', 38186, 'LICENCE - Droit',
     6, 'nationale', 'Fiche nationale, 57 certificateurs', NULL, 'active', '2028-12-31',
     'https://www.francecompetences.fr/recherche/rncp/38186/', '2026-09-23'),

    ('RNCP38158', 38158, 'MASTER - Droit',
     7, 'nationale', 'Fiche nationale, 15 certificateurs', NULL, 'active', '2028-12-31',
     'https://www.francecompetences.fr/recherche/rncp/38158/', '2026-09-23'),

    ('RNCP39278', 39278, 'MASTER - Informatique',
     7, 'nationale', 'Fiche nationale, 67 certificateurs', NULL, 'active', '2029-08-31',
     'https://www.francecompetences.fr/recherche/rncp/39278/', '2026-09-23'),

    ('RNCP42368', 42368, 'MASTER - Management et administration des entreprises',
     7, 'nationale', 'Fiche nationale', NULL, 'active', '2031-04-02',
     'https://www.francecompetences.fr/recherche/rncp/42368/', '2026-09-23'),

    ('RNCP40116', 40116, 'LICENCE - Informatique',
     6, 'nationale', 'Fiche nationale, 57 certificateurs', NULL, 'active', '2029-12-31',
     'https://www.francecompetences.fr/recherche/rncp/40116/', '2026-09-23')
ON CONFLICT (code) DO NOTHING;

-- La chaîne de remplacement EPITECH.
UPDATE fiche_rncp SET remplace_par = 'RNCP42505' WHERE code = 'RNCP37985';

-- --- Rattachements -------------------------------------------------------

-- certificateur_verifie = TRUE signifie que l'établissement a été constaté
-- dans la liste des certificateurs de la fiche. FALSE signifie que le
-- rattachement est plausible mais pas établi : l'interface le dit.

INSERT INTO etablissement_rncp
    (etablissement_id, code_rncp, niveau, certificateur_verifie, note, verifie_le)
VALUES
    ('epita',      'RNCP40531', 'master',  TRUE,
     'Titre d''ingénieur de l''école, tous campus. La fiche ne distingue pas les campus.', '2026-09-23'),
    ('epitech',    'RNCP42505', 'master',  TRUE,
     'Titre de l''école, tous campus. La fiche ne distingue pas les campus.', '2026-09-23'),
    ('esiea_lille','RNCP39893', 'master',  TRUE,
     'Titre d''ingénieur de l''école, tous campus.', '2026-09-23'),
    ('insa_lyon',  'RNCP42247', 'master',  TRUE,
     'Spécialité informatique. Remplace la fiche RNCP40971, échue.', '2026-09-23'),
    ('tbs_toulouse','RNCP36421','master',  TRUE,
     'Programme Grande École.', '2026-09-23'),

    ('montpellier_droit', 'RNCP38186', 'licence', TRUE,
     'Fiche nationale de licence en droit. Université de Montpellier constatée parmi les certificateurs.', '2026-09-23'),
    ('montpellier_droit', 'RNCP38158', 'master',  TRUE,
     'Fiche nationale de master en droit. Université de Montpellier constatée parmi les certificateurs.', '2026-09-23'),

    ('univ_poitiers', 'RNCP38186', 'licence', TRUE,
     'Fiche nationale de licence en droit. Université de Poitiers constatée parmi les certificateurs.', '2026-09-23'),

    ('univ_lille_info', 'RNCP39278', 'master', TRUE,
     'Fiche nationale de master en informatique. Université de Lille constatée parmi les certificateurs.', '2026-09-23'),

    ('univ_nantes_gestion', 'RNCP42368', 'master', FALSE,
     'Nantes Université figure parmi les certificateurs, mais l''IAE propose plusieurs mentions de master : le rattachement à cette mention précise reste à confirmer.', '2026-09-23'),

    ('univ_toulouse3', 'RNCP40116', 'licence', FALSE,
     'Fiche nationale de licence en informatique. Le certificateur est listé sous « Université de Toulouse » à la suite du regroupement : la correspondance avec Toulouse III reste à confirmer par SIRET.', '2026-09-23')
ON CONFLICT (etablissement_id, code_rncp) DO NOTHING;
