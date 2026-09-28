"""L'endpoint /health répond et expose l'état du LLM sans le forcer."""

def test_health_repond(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # llm_actif est False dans le contexte de test (pas de clé configurée) —
    # le back doit rester utilisable et le déclarer honnêtement.
    assert body["llm_actif"] is False
    assert "guidé" in body["mode"]


def test_documentation_ouverte(client):
    """Les docs FastAPI répondent : l'API est explorable sans jeton."""
    r = client.get("/docs")
    assert r.status_code == 200
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    chemins = set(schema.get("paths", {}).keys())
    # Les grandes zones fonctionnelles sont toutes présentes.
    for attendu in [
        "/api/auth/register", "/api/auth/login", "/api/auth/me",
        "/api/orientation/chat", "/api/orientation/rapport",
        "/api/rncp/verify",
        "/api/roadmap/generate", "/api/roadmap/step",
        "/api/paiement/create", "/api/paiement/status",
        "/api/chatbot",
        "/api/aides/entretien", "/api/aides/contestation",
    ]:
        assert attendu in chemins, f"route manquante : {attendu}"
