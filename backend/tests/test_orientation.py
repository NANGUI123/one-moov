"""Sans clé Groq, le conseiller doit basculer en mode guidé sans se casser.

C'est un contrat fort du produit : « le service ne casse pas quand le
fournisseur d'IA est en panne ». Le test le vérifie.
"""


def test_chat_orientation_sans_llm_bascule_en_guide(client):
    r = client.post("/api/orientation/chat", json={
        "messages": [{"role": "user", "content": "Bonjour, je veux étudier en France"}],
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mode"] == "guidé"
    # Le mode guidé propose des choix structurés à afficher en boutons.
    assert "[CHOICES]" in data["content"] or data.get("pret") is True


def test_chat_orientation_progresse_avec_reponses(client):
    """Chaque réponse pousse la conversation vers la question suivante du guide."""
    messages = [
        {"role": "user", "content": "Bonjour"},
        {"role": "user", "content": "Licence obtenue"},
    ]
    r = client.post("/api/orientation/chat", json={"messages": messages})
    assert r.status_code == 200
    data = r.json()
    # On avance mais on n'a pas fini le guide en 2 réponses.
    assert data["mode"] == "guidé"


def test_formations_repond_avec_pistes_de_base(client):
    """Les formations viennent de la table (via l'ingestion seed) — pas du LLM."""
    r = client.post("/api/orientation/formations", json={
        "messages": [],
        "profil": {"domaine": "informatique", "niveau_vise": "master",
                    "budget_annuel": 5000, "villes_cibles": ["Paris"]},
    })
    # 503 si la table est vide (l'endpoint le documente) ; 200 sinon.
    # L'ingestion seed n'est pas garantie ici — on tolère les deux, tant
    # que la réponse est cohérente.
    if r.status_code == 200:
        data = r.json()
        assert isinstance(data["formations"], list)
        assert data["source"] == "base vérifiée (scoring déterministe)"
    else:
        assert r.status_code == 503
        assert "Référentiel" in r.json().get("detail", "")
