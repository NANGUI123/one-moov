"""La couverture du catalogue, et ce qu'on en dit à l'étudiant.

La promesse du produit est qu'un étudiant choisit sa formation, quelle
qu'elle soit, et reçoit des pistes qui lui correspondent. Le catalogue ne
couvre pas tout, et ne le couvrira jamais entièrement. Ce qui doit être
garanti, ce n'est donc pas la couverture : c'est que l'étudiant sache quand
elle manque.

Le défaut que ces tests ferment : un étudiant en architecture recevait dix
masters d'informatique, chacun présenté avec la mention « formation du
domaine » et son code RNCP, sans un mot sur le fait que son domaine était
absent de la base.
"""

import pytest

from app.data.ingestion.onisep import charger_formations
from app.models import Formation
from app.services.orientation_engine import domaines_couverts, top_formations


@pytest.fixture(scope="module", autouse=True)
def _catalogue():
    """Amorce le catalogue une fois pour ce fichier."""
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        if db.query(Formation).count() == 0:
            charger_formations(db, force=True)
        yield
    finally:
        db.close()


def test_le_catalogue_couvre_plusieurs_domaines(db):
    """Le produit ne vaut que si l'étudiant a un vrai choix de champ."""
    domaines = domaines_couverts(db)
    assert len(domaines) >= 10, f"catalogue trop étroit : {domaines}"


def test_un_domaine_couvert_rend_des_pistes_de_ce_domaine(db):
    pistes = top_formations(db, {"domaine": "Droit", "niveau": "master"}, k=5)
    assert pistes
    assert all(p["correspondance"] in ("domaine", "proche") for p in pistes)
    assert any("droit" in p["domaine"].lower() for p in pistes)


def test_un_domaine_absent_est_signale_et_non_maquille(db):
    """Le cœur du sujet : l'architecture n'est pas au catalogue.

    On accepte de proposer autre chose — un étudiant préfère une liste à un
    écran vide — mais chaque piste doit porter qu'elle est hors domaine.
    """
    pistes = top_formations(db, {"domaine": "Architecture", "niveau": "master"}, k=5)
    assert pistes, "on rend quand même des pistes"
    assert all(p["correspondance"] == "hors_domaine" for p in pistes)


def test_aucune_piste_hors_domaine_ne_pretend_correspondre(db):
    """L'ancien libellé par défaut annonçait « formation du domaine » même
    sans le moindre critère satisfait."""
    pistes = top_formations(db, {"domaine": "Architecture", "niveau": "master"}, k=10)
    for p in pistes:
        assert "domaine" not in p["explication"].lower() or "proche" in p["explication"].lower()


def test_les_pistes_du_domaine_passent_devant_les_autres(db):
    """Une formation hors sujet bien notée sur le niveau et le budget ne doit
    pas devancer une formation du bon domaine."""
    pistes = top_formations(db, {"domaine": "Informatique", "niveau": "master",
                                 "budget_annuel": 500}, k=10)
    rangs = [p["correspondance"] for p in pistes]
    premiers = rangs[:3]
    assert all(r in ("domaine", "proche") for r in premiers), rangs


def test_l_api_annonce_la_couverture_manquante(client, db):
    r = client.post("/api/orientation/formations",
                    json={"profil": {"domaine": "Architecture", "niveau": "master"},
                          "messages": []})
    assert r.status_code == 200
    c = r.json()["couverture"]
    assert c["couvert"] is False
    assert c["pistes_du_domaine"] == 0
    assert "Architecture" in c["message"]
    assert "RNCP" in c["message"], "on propose la vérification d'une école choisie"
    assert len(c["domaines_disponibles"]) >= 10


def test_l_api_ne_crie_pas_au_loup_sur_un_domaine_couvert(client, db):
    r = client.post("/api/orientation/formations",
                    json={"profil": {"domaine": "Informatique", "niveau": "master"},
                          "messages": []})
    c = r.json()["couverture"]
    assert c["couvert"] is True
    assert "message" not in c


def test_sans_domaine_declare_la_couverture_n_est_pas_en_defaut(client, db):
    """Un étudiant qui n'a pas encore de domaine ne doit pas recevoir un
    avertissement de couverture : il n'a rien demandé."""
    r = client.post("/api/orientation/formations",
                    json={"profil": {"niveau": "master"}, "messages": []})
    assert r.json()["couverture"]["couvert"] is True
