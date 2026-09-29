"""
routers/auth.py — Inscription / connexion sécurisées.

- Mot de passe : politique de robustesse + hachage bcrypt.
- Vérification d'e-mail à l'inscription : jeton à usage unique + lien.
  Envoi réel si SMTP configuré, sinon « mode démo » (le lien est renvoyé pour test).
- Connexion bloquée tant que l'e-mail n'est pas vérifié (si EMAIL_VERIFICATION_REQUISE).
- Réinitialisation de mot de passe par e-mail (jeton + page dédiée).
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.config import get_settings
from app.models import User, Piste, EmailVerification, AuthToken
from app.schemas import RegisterIn, LoginIn, EmailIn, TokenOut, PAYS_ACCEPTES
from app.security import (hash_password, verify_password, create_token,
                         valider_mot_de_passe, nouveau_jeton)
from app.services import mailer

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


# ── Helpers ────────────────────────────────────────────────────────
def _est_verifie(db: Session, user_id: int) -> bool:
    return db.query(EmailVerification).filter(EmailVerification.user_id == user_id).first() is not None


def _marquer_verifie(db: Session, user_id: int) -> None:
    if not _est_verifie(db, user_id):
        db.add(EmailVerification(user_id=user_id))
        db.commit()


def _emettre_jeton(db: Session, user_id: int, kind: str, heures: int = 24) -> str:
    tok = nouveau_jeton()
    db.add(AuthToken(user_id=user_id, kind=kind, token=tok,
                     expires_at=datetime.utcnow() + timedelta(hours=heures)))
    db.commit()
    return tok


def _consommer_jeton(db: Session, token: str, kind: str) -> User | None:
    row = (db.query(AuthToken)
           .filter(AuthToken.token == token, AuthToken.kind == kind, AuthToken.used == False)  # noqa: E712
           .first())
    if not row or row.expires_at < datetime.utcnow():
        return None
    row.used = True
    db.commit()
    return db.get(User, row.user_id)


def _base_publique() -> str:
    """Renvoie PUBLIC_BASE_URL, en s'assurant qu'elle a bien un schéma
    et un domaine résolvable depuis un navigateur.

    Trois cas gérés :
      - vide → `http://localhost:8000` (développement) ;
      - hostname sans schéma (`one-moov-api` ou `one-moov-api:10000`) →
        interprété comme un service Render interne : on retire le port,
        on ajoute `.onrender.com` si nécessaire, et on préfixe `https://`.
        Ce cas apparaît quand la variable est calculée par
        `fromService.host` ou `fromService.hostport` de Render : la valeur
        renvoyée est le hostname INTERNE, pas résolvable depuis un
        navigateur d'étudiant ;
      - URL déjà complète (`https://...`) → renvoyée telle quelle, sans
        le slash final.
    """
    b = (settings.PUBLIC_BASE_URL or "").strip().rstrip("/")
    if not b:
        return "http://localhost:8000"
    if b.startswith(("http://", "https://")):
        return b
    # Hostname bare : hostname:port ou hostname
    hote = b.split(":", 1)[0]
    if "." not in hote:
        # Nom de service Render interne → domaine public correspondant.
        hote = f"{hote}.onrender.com"
    return f"https://{hote}"


def _envoyer(db: Session, user: User, kind: str) -> dict:
    token = _emettre_jeton(db, user.id, kind)
    chemin = f"/api/auth/{'verify' if kind == 'verify' else 'reset'}?token={token}"
    absolu = f"{_base_publique()}{chemin}"
    if kind == "verify":
        sujet = "One Moov — vérifiez votre adresse e-mail"
        html = _mail_html("Bienvenue sur One Moov",
                          "Confirmez votre adresse e-mail pour activer votre compte :",
                          "Vérifier mon adresse", absolu)
    else:
        sujet = "One Moov — réinitialisation de votre mot de passe"
        html = _mail_html("Réinitialisation du mot de passe",
                          "Vous avez demandé à réinitialiser votre mot de passe :",
                          "Choisir un nouveau mot de passe", absolu)
    envoye = mailer.envoyer(user.email, sujet, html)
    # En mode démo (pas de SMTP), on renvoie le lien ABSOLU. Le front est
    # servi par Cloudflare Pages, le back par Render : un lien relatif
    # tomberait sur le SPA fallback de Cloudflare (qui rerouterait sur
    # « Créer un compte » au lieu de vérifier le jeton).
    return {"envoye": envoye, "demo_lien": None if envoye else absolu}


# ── Inscription / connexion ────────────────────────────────────────
@router.post("/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    err = valider_mot_de_passe(body.password)
    if err:
        raise HTTPException(422, err)
    # Le pays est optionnel dans le contrat (compat ancien front) mais s'il
    # est fourni, il doit être dans la liste des pays couverts.
    pays = body.pays_residence.strip()
    if pays and pays not in PAYS_ACCEPTES:
        raise HTTPException(
            422,
            f"Pays non couvert pour l'instant. Choisis parmi : {', '.join(sorted(PAYS_ACCEPTES))}.",
        )
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(409, "Un compte existe déjà avec cet e-mail")

    user = User(email=body.email.lower(), password_hash=hash_password(body.password),
                prenom=body.prenom.strip(), pays_residence=pays)
    db.add(user)
    db.commit()
    db.refresh(user)

    if not settings.EMAIL_VERIFICATION_REQUISE:
        _marquer_verifie(db, user.id)
        return {"needs_verification": False,
                "access_token": create_token(user.id, user.email), "token_type": "bearer",
                "prenom": user.prenom, "user_id": user.id}

    info = _envoyer(db, user, "verify")
    return {"needs_verification": True, "email": user.email,
            "envoye": info["envoye"], "demo_lien": info["demo_lien"]}


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "E-mail ou mot de passe incorrect")
    if settings.EMAIL_VERIFICATION_REQUISE and not _est_verifie(db, user.id):
        raise HTTPException(403, "E-mail non vérifié. Vérifiez votre boîte mail (ou renvoyez le lien).")
    return TokenOut(access_token=create_token(user.id, user.email),
                    prenom=user.prenom, user_id=user.id)


@router.post("/resend")
def resend(body: EmailIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if user and not _est_verifie(db, user.id):
        info = _envoyer(db, user, "verify")
        return {"ok": True, "envoye": info["envoye"], "demo_lien": info["demo_lien"]}
    return {"ok": True, "envoye": False, "demo_lien": None}


@router.get("/verify", response_class=HTMLResponse)
def verify(token: str, db: Session = Depends(get_db)):
    user = _consommer_jeton(db, token, "verify")
    if not user:
        return HTMLResponse(_page("Lien invalide ou expiré",
                                  "Ce lien de vérification n'est plus valide. Renvoyez-en un depuis l'application."), 400)
    _marquer_verifie(db, user.id)
    return HTMLResponse(_page("Adresse vérifiée ✅",
                              "Votre e-mail est confirmé. Vous pouvez revenir à One Moov et vous connecter."))


# ── Réinitialisation du mot de passe ───────────────────────────────
@router.post("/forgot")
def forgot(body: EmailIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if user:
        info = _envoyer(db, user, "reset")
        return {"ok": True, "envoye": info["envoye"], "demo_lien": info["demo_lien"]}
    # Réponse identique même si l'e-mail n'existe pas (anti-énumération).
    return {"ok": True, "envoye": False, "demo_lien": None}


@router.get("/reset", response_class=HTMLResponse)
def reset_page(token: str):
    return HTMLResponse(f"""<!doctype html><meta charset="utf-8"><title>Nouveau mot de passe</title>
    {_STYLE}
    <div class="box">
      <h2>Nouveau mot de passe</h2>
      <p>Choisissez un mot de passe (8 caractères min., au moins une lettre et un chiffre).</p>
      <form method="post" action="/api/auth/reset/confirm">
        <input type="hidden" name="token" value="{token}">
        <input class="inp" type="password" name="password" placeholder="Nouveau mot de passe" required>
        <button class="btn" type="submit">Valider</button>
      </form>
    </div>""")


@router.post("/reset/confirm", response_class=HTMLResponse)
async def reset_confirm(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    token = form.get("token", "")
    password = form.get("password", "")
    err = valider_mot_de_passe(password)
    if err:
        return HTMLResponse(_page("Mot de passe trop faible", err), 422)
    user = _consommer_jeton(db, token, "reset")
    if not user:
        return HTMLResponse(_page("Lien invalide ou expiré",
                                  "Ce lien de réinitialisation n'est plus valide."), 400)
    user.password_hash = hash_password(password)
    db.commit()
    return HTMLResponse(_page("Mot de passe mis à jour ✅",
                              "Vous pouvez revenir à One Moov et vous connecter avec votre nouveau mot de passe."))


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pistes = db.query(Piste).filter(Piste.user_id == user.id).all()
    return {
        "id": user.id, "email": user.email, "prenom": user.prenom,
        "pays_residence": user.pays_residence or "",
        "email_verifie": _est_verifie(db, user.id),
        "pistes": [{"id": p.id, "pays": p.pays, "voie": p.voie, "paid": p.paid} for p in pistes],
    }


@router.get("/pays")
def pays_disponibles():
    """La liste des pays couverts, avec drapeau et libellé Campus France.

    Le front lit cette route pour afficher les cartes de sélection à
    l'inscription. Publiée plutôt que codée en dur côté client : quand
    on ajoutera un troisième pays, il apparaîtra sans redéploiement front.
    """
    return {
        "pays": [
            {"code": "Cameroun", "libelle": "Cameroun",
             "campus_france": "Campus France Cameroun",
             "drapeau": "🇨🇲",
             "operateurs_paiement": ["MTN Mobile Money", "Orange Money"]},
            {"code": "Congo-Brazzaville", "libelle": "Congo-Brazzaville",
             "campus_france": "Campus France Congo",
             "drapeau": "🇨🇬",
             "operateurs_paiement": ["MTN Mobile Money", "Airtel Money"]},
        ],
    }


# ── Gabarits HTML ──────────────────────────────────────────────────
_STYLE = ("<style>body{font-family:system-ui;background:#0c1514;color:#e9f1ee;margin:0}"
          ".box{max-width:440px;margin:60px auto;padding:24px;background:#15211f;"
          "border:1px solid #28352f;border-radius:14px}h2{color:#7fcdc0}"
          ".inp{width:100%;padding:12px;margin:8px 0;border-radius:10px;border:1px solid #28352f;"
          "background:#1a2724;color:#e9f1ee;box-sizing:border-box}"
          ".btn{background:#5bb9ac;color:#04211d;border:0;border-radius:10px;padding:12px 18px;"
          "font-weight:700;cursor:pointer;width:100%}a{color:#7fcdc0}</style>")


def _page(titre: str, texte: str) -> str:
    return f"""<!doctype html><meta charset="utf-8"><title>{titre}</title>{_STYLE}
    <div class="box"><h2>{titre}</h2><p>{texte}</p></div>"""


def _mail_html(titre: str, texte: str, bouton: str, lien: str) -> str:
    return (f"<div style='font-family:system-ui;max-width:480px;margin:auto'>"
            f"<h2 style='color:#0f5b55'>{titre}</h2><p>{texte}</p>"
            f"<p><a href='{lien}' style='background:#0f5b55;color:#fff;padding:12px 20px;"
            f"border-radius:8px;text-decoration:none;display:inline-block'>{bouton}</a></p>"
            f"<p style='color:#666;font-size:13px'>Ou copiez ce lien : {lien}</p></div>")
