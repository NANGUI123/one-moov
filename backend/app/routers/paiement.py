"""
routers/paiement.py — Paiement du parcours (CinetPay). Prix unique < 100 €.

Flux : create (page hébergée) → l'étudiant paie en mobile money → webhook signé →
vérification serveur → déblocage du parcours (piste.paid = True), idempotent.
En SANDBOX, une page /sandbox permet de simuler la confirmation.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.config import get_settings
from app.models import User, Piste, Payment
from app.schemas import PaiementCreateIn
from app.services import cinetpay

router = APIRouter(prefix="/api/paiement", tags=["paiement"])
settings = get_settings()


@router.post("/create")
def create(body: PaiementCreateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(Piste, body.piste_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "Piste introuvable")
    if p.paid:
        return {"already_paid": True}

    tx = f"OM-{uuid.uuid4().hex[:16]}"
    pay = Payment(piste_id=p.id, user_id=user.id, transaction_id=tx,
                  amount_eur=settings.PRIX_PARCOURS_EUR, amount_fcfa=settings.prix_fcfa,
                  status="pending")
    db.add(pay)
    db.commit()
    init = cinetpay.init_payment(tx, settings.prix_fcfa,
                                 description="One Moov — parcours de mobilité")
    return {**init, "amount_eur": settings.PRIX_PARCOURS_EUR, "amount_fcfa": settings.prix_fcfa}


def _confirmer(db: Session, tx: str) -> bool:
    pay = db.query(Payment).filter(Payment.transaction_id == tx).first()
    if not pay:
        return False
    if pay.status == "paid":         # idempotence
        return True
    if cinetpay.verify(tx) == "ACCEPTED":
        pay.status = "paid"
        piste = db.get(Piste, pay.piste_id)
        if piste:
            piste.paid = True
        db.commit()
        return True
    return False


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    """Notification CinetPay (form-urlencoded : cpm_trans_id)."""
    form = await request.form()
    tx = form.get("cpm_trans_id") or form.get("transaction_id") or ""
    ok = _confirmer(db, tx) if tx else False
    return {"received": True, "transaction_id": tx, "paid": ok}


@router.api_route("/retour", methods=["GET", "POST"], response_class=HTMLResponse)
async def retour(request: Request, tx: str = "", db: Session = Depends(get_db)):
    """Page où CinetPay renvoie l'étudiant après le paiement (selon les cas en
    GET ou en POST). On revérifie auprès de CinetPay avant d'afficher quoi que ce soit."""
    if not tx and request.method == "POST":
        form = await request.form()
        tx = form.get("transaction_id") or form.get("cpm_trans_id") or ""
    ok = _confirmer(db, tx) if tx else False
    titre = "✅ Paiement confirmé" if ok else "⏳ Paiement en cours de confirmation"
    texte = ("Votre parcours de mobilité est débloqué."
             if ok else "Si vous avez bien payé, la confirmation arrive en général "
                        "en quelques minutes.")
    return HTMLResponse(
        f"<!doctype html><meta charset='utf-8'><title>{titre}</title>"
        f"<div style='font-family:system-ui;max-width:420px;margin:60px auto;text-align:center'>"
        f"<h2>{titre}</h2><p>{texte}</p>"
        f"<p><a href='/' style='color:#0e6b5c;font-weight:700'>Revenir à One Moov</a></p></div>")


@router.get("/status")
def status(piste_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(Piste, piste_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "Piste introuvable")
    return {"piste_id": p.id, "paid": p.paid}


# ── SANDBOX (démo sans compte marchand) ────────────────────────────
@router.get("/sandbox", response_class=HTMLResponse)
def sandbox(tx: str):
    if cinetpay.is_live():
        raise HTTPException(404)
    montant = f"{settings.prix_fcfa:,}".replace(",", " ")
    return f"""<!doctype html><meta charset="utf-8"><title>Paiement (sandbox)</title>
    <div style="font-family:system-ui;max-width:420px;margin:60px auto;text-align:center">
      <h2>Paiement One Moov — SANDBOX</h2>
      <p>Transaction {tx}<br>Montant : {montant} FCFA</p>
      <p>Simulez le résultat du paiement mobile money :</p>
      <form method="post" action="/api/paiement/sandbox/confirm">
        <input type="hidden" name="tx" value="{tx}">
        <button style="padding:12px 24px;background:#0f5b55;color:#fff;border:0;border-radius:8px;font-size:16px">
          Payer (simuler un succès)</button>
      </form>
    </div>"""


@router.post("/sandbox/confirm", response_class=HTMLResponse)
async def sandbox_confirm(request: Request, db: Session = Depends(get_db)):
    if cinetpay.is_live():
        raise HTTPException(404)
    form = await request.form()
    tx = form.get("tx", "")
    ok = _confirmer(db, tx)
    return HTMLResponse(
        f"<div style='font-family:system-ui;text-align:center;margin-top:60px'>"
        f"<h2>{'✅ Paiement confirmé' if ok else '❌ Échec'}</h2>"
        f"<p>Vous pouvez fermer cette page et revenir à votre parcours.</p></div>")
