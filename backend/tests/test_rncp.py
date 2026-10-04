"""Vérification RNCP.

Sans RNCP_LLM_API_KEY, l'endpoint doit tomber sur le repli local
(rncp_client). Le repli ne trouvera rien dans une base vide, mais il doit
répondre — pas planter.
"""


def test_verify_rncp_sans_llm_web_repond(client):
    r = client.post("/api/rncp/verify", json={
        "intitule": "Master Data Science", "etablissement": "EPITA",
        "code_rncp": "", "piste_id": None,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    # Contrat minimal : le repli renvoie un statut normalisé — actif, expiré,
    # absent, ou indéterminé quand ni fiche ni code n'ont pu être résolus.
    assert data["statut"] in ("actif", "expire", "absent", "indetermine")
    assert "message" in data
    # La fiche pointe vers France Compétences comme source légale.
    assert "source" in data


def test_verify_rncp_par_code(client):
    r = client.post("/api/rncp/verify", json={
        "intitule": "", "etablissement": "", "code_rncp": "RNCP38363",
    })
    assert r.status_code == 200
    data = r.json()
    # Même contrat même quand le code est vide côté base.
    assert data["statut"] in ("actif", "expire", "absent", "indetermine")


def test_verify_rncp_tolere_champs_vides(client):
    r = client.post("/api/rncp/verify", json={
        "intitule": "", "etablissement": "", "code_rncp": "",
    })
    # 422 acceptable si le contrat valide, 200 acceptable si le service
    # traite l'entrée vide — les deux sont défendables.
    assert r.status_code in (200, 422), r.text


# --------------------------------------------- l'ordre de consultation

def test_la_base_est_consultee_avant_le_modele(db, client, monkeypatch):
    """Le principe du produit : la donnée fait autorité, le modèle complète.

    Si la base tranche, le modèle ne doit pas être appelé du tout — sinon on
    paie un appel et on prend le risque d'une réponse qui contredit la base.
    """
    from app.routers import rncp as routeur
    from app.services import rncp_client, rncp_web

    appels_modele = []
    monkeypatch.setattr(rncp_web, "disponible", lambda: True)
    monkeypatch.setattr(rncp_web, "verifier",
                        lambda **kw: appels_modele.append(kw) or {"statut": "actif"})
    monkeypatch.setattr(rncp_client, "verifier",
                        lambda *a, **k: {"statut": "actif", "code_rncp": "RNCP35000"})

    r = client.post("/api/rncp/verify", json={"intitule": "Master data"})
    assert r.status_code == 200
    assert appels_modele == [], "la base a tranché, le modèle ne devait pas être appelé"
    assert r.json()["origine"] == "base_officielle"
    assert r.json()["statut_confiance"] == "confirme"


def test_le_modele_complete_seulement_quand_la_base_ignore(db, client, monkeypatch):
    from app.services import rncp_client, rncp_web

    monkeypatch.setattr(rncp_web, "disponible", lambda: True)
    monkeypatch.setattr(rncp_web, "verifier",
                        lambda **kw: {"statut": "actif", "code_rncp": "RNCP99999"})
    monkeypatch.setattr(rncp_client, "verifier",
                        lambda *a, **k: {"statut": "indetermine"})

    d = client.post("/api/rncp/verify", json={"intitule": "École inconnue"}).json()
    assert d["origine"] == "modele_web"
    assert d["statut_confiance"] == "non confirme"
    assert "francecompetences.fr" in d["avertissement"]


def test_une_reponse_de_modele_ne_deconseille_jamais(db, client, monkeypatch):
    """Déconseiller une école sur la foi d'un modèle engagerait une décision
    que la donnée ne soutient pas."""
    from app.services import rncp_client, rncp_web

    monkeypatch.setattr(rncp_web, "disponible", lambda: True)
    monkeypatch.setattr(rncp_web, "verifier",
                        lambda **kw: {"statut": "expire", "deconseille": True})
    monkeypatch.setattr(rncp_client, "verifier",
                        lambda *a, **k: {"statut": "indetermine"})

    assert client.post("/api/rncp/verify",
                       json={"intitule": "X"}).json()["deconseille"] is False


def test_une_panne_du_modele_laisse_la_reponse_de_la_base(db, client, monkeypatch):
    from app.services import rncp_client, rncp_web

    def _casse(**kw):
        raise RuntimeError("502")

    monkeypatch.setattr(rncp_web, "disponible", lambda: True)
    monkeypatch.setattr(rncp_web, "verifier", _casse)
    monkeypatch.setattr(rncp_client, "verifier",
                        lambda *a, **k: {"statut": "indetermine", "url_fiche": "https://x"})

    d = client.post("/api/rncp/verify", json={"intitule": "X"}).json()
    assert d["statut"] == "indetermine"
    assert d["url_fiche"] == "https://x"
