"""
main.py — Application One Moov (API FastAPI).

v1 web. LLM : Groq (cascade de modèles) + mode guidé. Données : PostgreSQL.
Principe : les faits viennent de la base, le LLM ne fait que mettre en forme.
"""
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import get_settings
from app.db import init_db
from app.services.llm import get_llm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("onemoov")
settings = get_settings()

app = FastAPI(title="One Moov API", version="1.0.0",
              description="Orientation gratuite + parcours de mobilité (Groq · PostgreSQL)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup():
    init_db()
    # Initialise les tables RAG (idempotent) : les deux agents en dépendent.
    try:
        from app.db import SessionLocal
        from app.services import rag as _rag
        with SessionLocal() as _db:
            _rag.init_tables(_db)
            etat = _rag.etat(_db)
        logger.info(f"RAG : {etat}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Init RAG différée : {e}")
    llm = get_llm()
    logger.info(f"Base : {settings.db_url.split('://')[0]} | LLM Groq actif : {llm.available} "
                f"| modèles : {llm.models}")
    # État des notifications : e-mail (SMTP/Brevo) et WhatsApp (Twilio).
    # Rend visible depuis les logs si un fournisseur reste en mode démo,
    # ce qui évite de deviner pourquoi les mails ne partent pas.
    try:
        from app.services import notifications as _notif
        etat_email = "actif" if _notif.email_configure() else "MODE DÉMO (SMTP absent)"
        etat_wa = "actif" if _notif.whatsapp_configure() else "MODE DÉMO (Twilio absent)"
        logger.info(f"Notifications : e-mail = {etat_email} | WhatsApp = {etat_wa}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"État notifications indéterminé : {e}")


@app.get("/health")
def health():
    llm = get_llm()
    return {"status": "ok", "llm_actif": llm.available, "modeles": llm.models,
            "mode": "IA" if llm.available else "guidé (sans clé Groq)"}


# ── Routers ───────────────────────────────────────────────────────
from app.routers import auth, metrics  # noqa: E402
app.include_router(auth.router)
app.include_router(metrics.router)

for _mod in ("pistes", "orientation", "rncp", "roadmap", "paiement", "chatbot", "aides"):
    try:
        _m = __import__(f"app.routers.{_mod}", fromlist=["router"])
        app.include_router(_m.router)
    except ImportError as e:                   # router pas encore créé
        logger.info(f"Router '{_mod}' non chargé : {e}")


# ── Frontend buildé (prod) ────────────────────────────────────────
_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    if (_dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        return FileResponse(str(_dist / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
