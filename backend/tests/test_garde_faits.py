"""Le garde-fou qui empêche un montant ou un délai de sortir du modèle.

Ces tests font partie de la chaîne : s'ils échouent, la construction échoue.
C'est ce qui transforme « le modèle ne doit pas inventer de montant » d'une
consigne adressée au modèle en une propriété du système.

Les tests de faux positifs comptent autant que les autres. Un garde-fou qui
bloque des réponses correctes est désactivé dans la semaine, et la règle
redevient une intention.
"""

from app.services import garde_faits as g

FAITS = (
    "Frais de dossier Campus France : 85 000 FCFA. "
    "Ressources mensuelles à justifier : 615 € par mois. "
    "Délai de validation du VLS-TS : 90 jours après l'arrivée."
)


# --------------------------------------------------------- ce qui doit passer

def test_une_reponse_sans_chiffre_passe():
    assert g.verifier("Prépare tes relevés de notes et ton passeport.", FAITS) == []


def test_un_montant_repris_des_faits_passe():
    texte = "Les frais de dossier sont de 85 000 FCFA, à régler avant le dépôt."
    assert g.verifier(texte, FAITS) == []


def test_un_delai_repris_des_faits_passe():
    assert g.verifier("Tu as 90 jours pour valider ton VLS-TS.", FAITS) == []


def test_une_autre_typographie_du_meme_montant_passe():
    """« 85000 FCFA » et « 85 000 FCFA » sont le même montant.

    Sans cette normalisation, le garde-fou bloquerait une réponse juste dès
    que le modèle écrit les milliers autrement que la base.
    """
    assert g.verifier("Compte 85000 FCFA de frais.", FAITS) == []


def test_un_montant_donne_par_l_etudiant_passe():
    """L'agent a le droit de reprendre ce que l'étudiant vient de dire."""
    message = "j'ai un budget de 700 € par mois"
    assert g.verifier("Avec 700 € par mois, vise une ville moyenne.", FAITS, message) == []


def test_un_nombre_sans_unite_engageante_passe():
    """« étape 4 », « 7 vœux » : des nombres, pas des engagements."""
    texte = "À l'étape 4, tu peux déposer jusqu'à 7 vœux dans ton espace."
    assert g.verifier(texte, FAITS) == []


# --------------------------------------------------------- ce qui doit bloquer

def test_un_montant_invente_est_detecte():
    v = g.verifier("Prévois environ 450 € de frais de traduction.", FAITS)
    assert len(v) == 1
    assert v[0].nature == "montant"
    assert v[0].valeur == "450"


def test_un_delai_invente_est_detecte():
    v = g.verifier("La réponse arrive sous 21 jours en général.", FAITS)
    assert [x.nature for x in v] == ["duree"]


def test_un_taux_invente_est_detecte():
    """Un taux d'insertion inventé vend une formation."""
    v = g.verifier("Cette école affiche 92 % d'insertion à six mois.", FAITS)
    assert [x.nature for x in v] == ["taux"]


def test_plusieurs_inventions_sont_toutes_remontees():
    texte = "Compte 450 € de dossier, une réponse sous 21 jours, et 92 % d'insertion."
    assert len(g.verifier(texte, FAITS)) == 3


def test_le_meme_montant_invente_deux_fois_ne_compte_qu_une_alerte():
    texte = "Il faut 450 €. Oui, 450 € exactement."
    assert len(g.verifier(texte, FAITS)) == 1


def test_sans_aucun_fait_fourni_tout_montant_est_une_invention():
    """Le cas le plus dangereux : l'agent répond alors que la base n'a rien
    donné. Il ne doit rien pouvoir avancer de chiffré."""
    assert len(g.verifier("Les frais sont de 85 000 FCFA.", "")) == 1


# ------------------------------------------------------------- le remplacement

def test_filtrer_laisse_passer_une_reponse_saine():
    texte = "Les frais de dossier sont de 85 000 FCFA."
    sortie, violations = g.filtrer(texte, FAITS, endpoint="test")
    assert sortie == texte and violations == []


def test_filtrer_remplace_une_reponse_fautive_au_lieu_de_la_rapiecer():
    """On ne retire pas le chiffre pour sauver la phrase : la phrase était
    construite autour de lui, elle induirait encore en erreur."""
    sortie, violations = g.filtrer("Prévois 450 € de traduction.", FAITS,
                                   endpoint="test")
    assert violations
    assert "450" not in sortie
    assert "source officielle" in sortie


# -------------------------------------------------- la normalisation elle-même

def test_normalisation_des_separateurs():
    n = g._normaliser
    assert n("85 000") == n("85000") == n("85.000") == "85000"
    assert n("1 234,50") == n("1234.50") == "1234.5"
    assert n("615") == "615"
