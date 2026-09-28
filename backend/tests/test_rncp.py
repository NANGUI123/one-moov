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
