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
    etat = llm.etat()
    logger.info(
        f"Base : {settings.db_url.split('://')[0]} | niveaux IA : "
        f"{etat['niveaux_avec_ia']}/2 | nominal {etat['principal']['modeles']} "
        f"actif={etat['principal']['actif']} | secours actif={etat['secours']['actif']}"
    )
    if etat["niveaux_avec_ia"] < 2:
        logger.warning(
            "Pas de secours chez un second hébergeur : une panne du "
            "fournisseur nominal fait tomber directement en mode guidé. "
            "Poser SECOURS_API_KEY pour l'activer."
        )
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

    # Sync RNCP en arrière-plan si la base est vide. On ne bloque JAMAIS le
    # démarrage (Render tue le service au-delà de 30s d'inactivité HTTP), et
    # une erreur de téléchargement n'empêche pas l'app de servir : le
    # fallback rncp_client renvoie un lien direct francecompetences.fr en
    # attendant la fin du sync. L'étudiant ne voit jamais l'instruction
    # technique « python -m app.scripts.sync_rncp ».
    import threading
    def _sync_rncp_bg():
        try:
            from app.db import SessionLocal
            from app.models import RncpFiche
            from app.data.ingestion import rncp as _rncp_ingest
            with SessionLocal() as _db:
                if _db.query(RncpFiche).count() > 0:
                    logger.info("RNCP : base déjà peuplée, sync ignoré")
                    return
                logger.info("RNCP : sync en arrière-plan démarré…")
                n = _rncp_ingest.sync(_db)
                logger.info(f"RNCP : sync terminé — {n} fiches chargées")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"RNCP : sync arrière-plan échoué ({e}). "
                           "Le fallback lien direct France Compétences prend le relais.")
    threading.Thread(target=_sync_rncp_bg, name="rncp-sync", daemon=True).start()


@app.get("/health")
def health():
    llm = get_llm()
    etat = llm.etat()
    return {"status": "ok", "llm_actif": llm.available, "modeles": llm.models,
            "mode": "IA" if llm.available else "guidé (sans clé de modèle)",
            # Le détail des niveaux : c'est ce qui permet de voir d'un coup
            # d'œil qu'on tourne sans filet plutôt que de le découvrir en
            # panne.
            "repli": etat}


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
