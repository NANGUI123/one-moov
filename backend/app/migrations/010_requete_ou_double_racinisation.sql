-- ============================================================================
-- Correction : requete_ou racinisait deux fois.
--
-- Le défaut
-- ---------
-- La fonction découpait le texte en lexèmes avec to_tsvector — qui racinise
-- déjà — puis repassait le résultat à to_tsquery('french', …), qui racinise
-- une seconde fois. Deux exemples mesurés :
--
--     to_tsvector('french', 'mon dossier')  ->  'dossi'      (dans l'index)
--     requete_ou('mon dossier')             ->  'doss'       (dans la requête)
--
-- Les deux ne se rencontrent jamais. Toute question contenant un mot dont la
-- racine se racinise encore ne remontait rien du tout — silencieusement,
-- sans erreur, avec un simple résultat vide.
--
-- Mesuré sur le jeu d'évaluation : « quels papiers je dois réunir pour mon
-- dossier » renvoyait zéro passage alors que quatre passages parlent du
-- dossier.
--
-- La correction
-- -------------
-- On cite chaque lexème et on convertit la chaîne en tsquery par un cast,
-- qui n'applique aucune normalisation — contrairement à to_tsquery. Les
-- lexèmes sortent de l'index tels quels et y rentrent tels quels.
--
-- quote_literal protège aussi les lexèmes contenant une apostrophe ou un
-- caractère que la syntaxe tsquery interpréterait.
-- ============================================================================

CREATE OR REPLACE FUNCTION requete_ou(p_texte TEXT)
RETURNS tsquery AS $$
DECLARE
    lexemes TEXT;
BEGIN
    SELECT string_agg(quote_literal(lexeme), ' | ')
      INTO lexemes
      FROM unnest(
             tsvector_to_array(to_tsvector('french', COALESCE(p_texte, '')))
           ) AS lexeme;

    IF lexemes IS NULL OR lexemes = '' THEN
        RETURN NULL;   -- un texte fait uniquement de mots vides
    END IF;

    -- Cast direct : aucune racinisation supplémentaire.
    RETURN lexemes::tsquery;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
