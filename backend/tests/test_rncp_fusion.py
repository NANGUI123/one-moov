"""Fusion des lignes de l'export RNCP par code.

L'archive de France Compétences peut répéter un même code dans plusieurs
CSV (fiche, certificateurs, remplacements). Une ligne annexe, sans état ni
intitulé, ne doit jamais devenir la fiche retenue par la vérification.
"""
from datetime import date, timedelta

from app.data.ingestion.rncp import fusionner, parse_csv_bytes
from app.models import RncpFiche
from app.services import rncp_client as rc

DEMAIN = (date.today() + timedelta(days=1)).strftime("%d/%m/%Y")

FICHES = (f"Numero_Fiche;Intitule;Actif;Nomenclature_Europe_Niveau;Date_Fin_Enregistrement\n"
          f"RNCP50001;Master Économie appliquée;ACTIVE;NIV7;{DEMAIN}\n").encode()
CERTIFICATEURS = ("Numero_Fiche;Nom_Certificateur\n"
                  "RNCP50001;UNIVERSITE DE NANTES\n"
                  "RNCP50001;UNIVERSITE DE LILLE\n").encode()
REMPLACEMENTS = ("Numero_Fiche;Nouvelle_Certification\n"
                 "RNCP50001;RNCP50002\n").encode()


def _lignes():
    return (parse_csv_bytes(REMPLACEMENTS) + parse_csv_bytes(CERTIFICATEURS)
            + parse_csv_bytes(FICHES))


def test_une_seule_ligne_par_code():
    fiches = fusionner(_lignes())
    assert [f["code_rncp"] for f in fiches] == ["RNCP50001"]


def test_les_lignes_annexes_ne_rendent_pas_la_fiche_inactive():
    [f] = fusionner(_lignes())
    assert f["actif"] is True
    assert f["intitule"] == "Master Économie appliquée"
    assert f["date_fin"] == DEMAIN


def test_les_certificateurs_et_le_remplacant_sont_reunis():
    [f] = fusionner(_lignes())
    assert f["certificateurs"] == "UNIVERSITE DE NANTES ; UNIVERSITE DE LILLE"
    assert f["remplace_par"] == "RNCP50002"


def test_sans_etat_declare_nulle_part_la_fiche_n_est_pas_active():
    [f] = fusionner(parse_csv_bytes(CERTIFICATEURS))
    assert f["actif"] is False


def test_verdict_sur_une_fiche_fusionnee(db):
    [f] = fusionner(parse_csv_bytes(FICHES) + parse_csv_bytes(CERTIFICATEURS))
    fiche = RncpFiche(date_sync=str(date.today()), **f)
    db.add(fiche)
    db.commit()
    try:
        r = rc.verifier(db, code_rncp="RNCP50001", etablissement="Université de Lille")
        assert r["statut"] == "actif"
        assert r["certificateurs"] == ["UNIVERSITE DE NANTES", "UNIVERSITE DE LILLE"]
        assert r["reserve"] == ""
        r = rc.verifier(db, code_rncp="RNCP50001", etablissement="INSA Lyon")
        assert "sous ce nom" in r["reserve"]
    finally:
        db.delete(fiche)
        db.commit()


def test_au_dela_de_trois_certificateurs_le_message_donne_leur_nombre(db):
    noms = " ; ".join(f"UNIVERSITE {i}" for i in range(57))
    fiche = RncpFiche(code_rncp="RNCP50003", actif=True, etat="ACTIVE",
                      intitule="Master national", niveau="7", certificateurs=noms,
                      date_fin=DEMAIN, remplace_par="", date_sync=str(date.today()))
    db.add(fiche)
    db.commit()
    try:
        r = rc.verifier(db, code_rncp="RNCP50003")
        assert "57 certificateurs" in r["message"]
        assert len(r["certificateurs"]) == 57
    finally:
        db.delete(fiche)
        db.commit()
