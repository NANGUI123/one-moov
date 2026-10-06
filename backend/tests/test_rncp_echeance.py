"""Échéance, remplacement et rattachement à l'établissement.

Le défaut à l'origine de ces tests : un master d'économie et gestion dont
l'enregistrement était échu s'affichait « actif et reconnu par l'État ».
La colonne d'état de l'export le déclarait encore actif, et le verdict ne
regardait que cette colonne. La date de fin était récupérée, stockée,
affichée, et jamais comparée à quoi que ce soit.

Chaque test ci-dessous échoue sur le code d'avant.
"""
from datetime import date, timedelta

import pytest

from app.models import RncpFiche
from app.services import rncp_client as rc


HIER = (date.today() - timedelta(days=1)).strftime("%d/%m/%Y")
DEMAIN = (date.today() + timedelta(days=1)).strftime("%d/%m/%Y")


@pytest.fixture()
def fiches(db):
    """Quatre fiches qui couvrent les cas réels, effacées après le test."""
    lot = [
        # Le cas constaté : échue, mais l'export la dit encore active.
        RncpFiche(code_rncp="RNCP31989", actif=True, etat="Active",
                  intitule="MASTER - Économie et gestion", niveau="7",
                  certificateurs="Fiche nationale, 57 certificateurs",
                  date_fin=HIER, remplace_par="", date_sync=str(date.today())),
        # Échue et remplacée : il faut envoyer l'étudiant sur la remplaçante.
        RncpFiche(code_rncp="RNCP37985", actif=True, etat="Active",
                  intitule="Expert en technologies de l'information",
                  niveau="7", certificateurs="EPITECH", date_fin=HIER,
                  remplace_par="RNCP42505", date_sync=str(date.today())),
        # Celle qui va bien.
        RncpFiche(code_rncp="RNCP42505", actif=True, etat="Active",
                  intitule="Expert en ingénierie logicielle", niveau="7",
                  certificateurs="EPITECH", date_fin=DEMAIN,
                  remplace_par="", date_sync=str(date.today())),
        # Un master sans rapport, pour vérifier qu'il n'est pas retenu sur
        # le seul nom de l'université.
        RncpFiche(code_rncp="RNCP42368", actif=True, etat="Active",
                  intitule="MASTER - Management et administration des entreprises",
                  niveau="7", certificateurs="Université de Nantes",
                  date_fin=DEMAIN, remplace_par="", date_sync=str(date.today())),
    ]
    db.add_all(lot)
    db.commit()
    yield db
    for f in lot:
        db.delete(f)
    db.commit()


# ------------------------------------------------- la date fait autorité

def test_une_fiche_echue_est_expiree_meme_declaree_active(fiches):
    """Le cœur du défaut. L'état déclaré ne peut pas écraser l'échéance."""
    r = rc.verifier(fiches, code_rncp="RNCP31989")
    assert r["statut"] == "expire"
    assert r["deconseille"] is True
    assert "échu" in r["message"]


def test_une_fiche_en_cours_reste_active(fiches):
    r = rc.verifier(fiches, code_rncp="RNCP42505")
    assert r["statut"] == "actif"
    assert r["deconseille"] is False


@pytest.mark.parametrize("valeur,attendu", [
    ("31/08/2020", True),      # format courant de l'export
    ("2020-08-31", True),      # format ISO, croisé sur certains exports
    ("31/08/2099", False),
    ("2099-08-31", False),
    ("", False),               # pas de date : l'état déclaré tranche
    ("à définir", False),      # illisible n'est pas dépassé
])
def test_lecture_des_formats_de_date(valeur, attendu):
    assert rc.echue(valeur) is attendu


def test_une_date_illisible_ne_condamne_pas_la_fiche(fiches, db):
    """Un défaut de format de l'export ne doit pas faire déconseiller une
    école. On se trompe du côté de l'étudiant, pas de celui du verdict."""
    f = RncpFiche(code_rncp="RNCP99001", actif=True, etat="Active",
                  intitule="Master test", niveau="7", certificateurs="X",
                  date_fin="non communiquée", remplace_par="",
                  date_sync=str(date.today()))
    db.add(f)
    db.commit()
    try:
        assert rc.verifier(db, code_rncp="RNCP99001")["statut"] == "actif"
    finally:
        db.delete(f)
        db.commit()


# ------------------------------------------------------- le remplacement

def test_une_fiche_remplacee_renvoie_vers_la_remplacante(fiches):
    r = rc.verifier(fiches, code_rncp="RNCP37985")
    assert r["statut"] == "expire"
    assert r["remplace_par"] == "RNCP42505"
    assert "RNCP42505" in r["message"]
    assert "/recherche/rncp/42505/" in r["url_fiche"], \
        "le lien doit mener à la fiche en vigueur, pas à la périmée"


def test_le_code_de_la_remplacante_est_lu_dans_l_export():
    from app.data.ingestion.rncp import _remplacant
    assert _remplacant({"Nouvelle_Certification": "RNCP42505"}) == "RNCP42505"
    assert _remplacant({"Nouvelle_Certification": "rncp 42505, RNCP40531"}) \
        == "RNCP42505"
    assert _remplacant({"Nouvelle_Certification": ""}) == ""
    assert _remplacant({}) == ""


# ------------------------------------------- un état absent n'est pas actif

def test_un_etat_absent_ne_vaut_plus_actif():
    """Le défaut valait « actif » par défaut : un faux positif silencieux,
    et le pire sens possible pour un défaut de données."""
    from app.data.ingestion.rncp import parse_csv_bytes
    csv = ("Numero_Fiche;Intitule;Date_Fin_Enregistrement\n"
           "RNCP12345;Master sans état;31/12/2099\n").encode()
    [fiche] = parse_csv_bytes(csv)
    assert fiche["actif"] is False


def test_un_etat_present_est_respecte():
    from app.data.ingestion.rncp import parse_csv_bytes
    csv = ("Numero_Fiche;Intitule;Actif;Date_Fin_Enregistrement\n"
           "RNCP12345;Master actif;ACTIVE;31/12/2099\n"
           "RNCP12346;Master inactif;INACTIVE;31/12/2099\n").encode()
    actif, inactif = parse_csv_bytes(csv)
    assert actif["actif"] is True
    assert inactif["actif"] is False


# ------------------------------------- l'établissement ne suffit pas à élire

def test_le_nom_de_l_universite_seul_ne_retient_aucune_fiche(fiches):
    """Le certificateur valait trois points, soit le seuil : n'importe quel
    intitulé associé à « Université de Nantes » tombait sur son premier
    master."""
    r = rc.verifier(fiches, intitule="Licence de biologie marine",
                    etablissement="Université de Nantes")
    assert r["statut"] == "indetermine"
    assert "code RNCP" in r["message"]


def test_un_intitule_qui_correspond_vraiment_est_retenu(fiches):
    r = rc.verifier(fiches, intitule="Management et administration des entreprises",
                    etablissement="Université de Nantes")
    assert r["code_rncp"] == "RNCP42368"


def test_une_fiche_active_ne_prime_plus_sur_la_bonne_fiche_expiree(fiches):
    """Le bonus « +1 si la fiche est active » poussait vers une fiche active
    au détriment de la fiche expirée recherchée, c'est-à-dire qu'il masquait
    exactement ce que cette vérification doit faire voir."""
    r = rc.verifier(fiches, intitule="Expert en technologies de l'information",
                    etablissement="EPITECH")
    assert r["code_rncp"] == "RNCP37985"
    assert r["statut"] == "expire"


# ------------------------------------------ fiche nationale et rattachement

def test_une_fiche_nationale_ne_prouve_rien_sur_l_etablissement(fiches):
    """Une fiche nationale couvre des dizaines d'universités. Le dire est
    plus honnête que de laisser l'étudiant conclure."""
    r = rc.verifier(fiches, code_rncp="RNCP31989",
                    etablissement="Université de Douala")
    assert r["reserve"]
    assert "n'est pas vérifié" in r["reserve"]


def test_un_etablissement_absent_des_certificateurs_est_signale(fiches):
    r = rc.verifier(fiches, code_rncp="RNCP42505",
                    etablissement="Université de Yaoundé")
    assert "ne figure pas parmi les certificateurs" in r["reserve"]


def test_le_bon_certificateur_ne_declenche_aucune_reserve(fiches):
    r = rc.verifier(fiches, code_rncp="RNCP42505", etablissement="EPITECH")
    assert r["reserve"] == ""


@pytest.mark.parametrize("certificateurs,etablissement,attendu", [
    ("EPITECH", "Epitech", True),
    ("EPITECH", "EPITA", False),
    ("Fiche nationale, 57 certificateurs", "Université de Lille", None),
    ("", "EPITECH", None),
    ("EPITECH", "", None),
])
def test_rattachement_a_l_etablissement(certificateurs, etablissement, attendu):
    assert rc.couvre_etablissement(certificateurs, etablissement) is attendu
