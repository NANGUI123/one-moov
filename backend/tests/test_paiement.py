"""Paiement : montant accepté par CinetPay et page de retour après paiement."""

import uuid

from app.models import Payment, Piste, User


def _paiement_en_attente(db) -> tuple[str, int]:
    u = User(email=f"pay-{uuid.uuid4().hex[:8]}@test.org", password_hash="x", prenom="T")
    db.add(u)
    db.commit()
    p = Piste(user_id=u.id)
    db.add(p)
    db.commit()
    tx = f"OM-{uuid.uuid4().hex[:16]}"
    db.add(Payment(piste_id=p.id, user_id=u.id, transaction_id=tx, status="pending"))
    db.commit()
    return tx, p.id


def test_le_prix_en_fcfa_est_un_multiple_de_5(settings):
    assert settings.prix_fcfa % 5 == 0
    assert abs(settings.prix_fcfa - settings.PRIX_PARCOURS_EUR * settings.TAUX_EUR_FCFA) < 5


def test_la_page_de_retour_confirme_le_paiement_en_get(client, db):
    tx, piste_id = _paiement_en_attente(db)
    r = client.get(f"/api/paiement/retour?tx={tx}")
    assert r.status_code == 200
    assert "Paiement confirmé" in r.text
    db.expire_all()
    assert db.get(Piste, piste_id).paid is True


def test_la_page_de_retour_accepte_le_post_de_cinetpay(client, db):
    tx, piste_id = _paiement_en_attente(db)
    r = client.post("/api/paiement/retour", data={"transaction_id": tx})
    assert r.status_code == 200
    assert "Paiement confirmé" in r.text


def test_une_transaction_inconnue_ne_confirme_rien(client):
    r = client.get("/api/paiement/retour?tx=OM-inexistante")
    assert r.status_code == 200
    assert "en cours de confirmation" in r.text
