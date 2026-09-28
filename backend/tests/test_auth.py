"""Cycle de vie d'un compte : inscription, vérification, connexion, /me.

En test, EMAIL_VERIFICATION_REQUISE=false : l'inscription rend un jeton
immédiatement (mode démo). En production, il faudrait d'abord suivre le
lien de vérification.
"""
import uuid


def _identifiant_unique() -> str:
    """Chaque test s'exécute avec une adresse propre : la table users est
    partagée entre tests et un doublon rendrait le test dépendant de l'ordre.

    On utilise `example.com`, RFC 2606 réservé aux exemples : le validateur
    pydantic-email refuse `.test` (TLD spécial) mais accepte `example.com`.
    """
    return f"test-{uuid.uuid4().hex[:12]}@example.com"


def test_inscription_puis_login(client):
    email = _identifiant_unique()
    r = client.post("/api/auth/register", json={
        "email": email, "password": "MotDePasse123", "prenom": "Ada",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    # Sans vérification obligatoire (mode démo test), le jeton est direct.
    assert "access_token" in data
    token = data["access_token"]

    # /me protégé, doit accepter le jeton.
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["prenom"] == "Ada"
    assert me.json()["email"] == email

    # Login refait le même jeton.
    login = client.post("/api/auth/login", json={
        "email": email, "password": "MotDePasse123",
    })
    assert login.status_code == 200
    assert "access_token" in login.json()


def test_login_avec_mauvais_mot_de_passe(client):
    email = _identifiant_unique()
    client.post("/api/auth/register", json={
        "email": email, "password": "MotDePasse123", "prenom": "Ada",
    })
    r = client.post("/api/auth/login", json={"email": email, "password": "faux"})
    assert r.status_code in (400, 401, 403), r.text


def test_me_sans_jeton(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_liste_des_pays_disponibles(client):
    """Le front lit /auth/pays pour afficher les cartes de sélection."""
    r = client.get("/api/auth/pays")
    assert r.status_code == 200
    data = r.json()
    codes = {p["code"] for p in data["pays"]}
    assert "Cameroun" in codes
    assert "Congo-Brazzaville" in codes
    # Chaque pays porte les infos que la carte affiche.
    for p in data["pays"]:
        for cle in ("code", "libelle", "campus_france", "drapeau", "operateurs_paiement"):
            assert cle in p, f"champ manquant : {cle}"
        assert len(p["operateurs_paiement"]) >= 1


def test_inscription_sans_pays_reste_acceptee(client):
    """Compat ascendante : un ancien front sans champ pays doit passer."""
    email = _identifiant_unique()
    r = client.post("/api/auth/register", json={
        "email": email, "password": "MotDePasse123", "prenom": "Ada",
    })
    assert r.status_code == 200


def test_inscription_avec_pays_couvert(client):
    """Le pays choisi est retourné par /me après inscription + connexion."""
    email = _identifiant_unique()
    r = client.post("/api/auth/register", json={
        "email": email, "password": "MotDePasse123", "prenom": "Ada",
        "pays_residence": "Cameroun",
    })
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["pays_residence"] == "Cameroun"


def test_inscription_avec_pays_non_couvert(client):
    """Un pays hors périmètre est refusé avec message clair."""
    email = _identifiant_unique()
    r = client.post("/api/auth/register", json={
        "email": email, "password": "MotDePasse123", "prenom": "Ada",
        "pays_residence": "Freedonia",
    })
    assert r.status_code == 422
    assert "couvert" in r.json()["detail"].lower()
