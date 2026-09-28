"""One Moov, API.

Deux agents conversationnels adossés à une base de référentiel, à des faits
vérifiés, à un répertoire RNCP et à une base de connaissance procédurale.

Ce que le serveur conserve, et rien de plus : une adresse e-mail, une
empreinte de mot de passe, le projet d'études et la feuille de route d'un
compte. Aucune conversation avec les agents n'est enregistrée, pour personne,
même connecté. La suppression d'un compte efface tout, sans corbeille.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import JWT_SECRET_EPHEMERE, settings
from app.routers import (
    chatbot, comptes, orientation, paiements, rncp, synchronisation, systeme,
)
from app.services import quotas
from app.services.metriques import compteurs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s : %(message)s",
)

logger = logging.getLogger(__name__)

if JWT_SECRET_EPHEMERE:
    logger.warning(
        "JWT_SECRET absent : un secret éphémère a été tiré au hasard. "
        "Les sessions ne survivront pas au redémarrage. "
        "À poser explicitement en production."
    )

app = FastAPI(
    title="One Moov",
    description="Accompagnement des étudiants d'Afrique centrale vers les études en France.",
    version="3.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.origines_autorisees.split(",") if o.strip()],
    allow_credentials=False,   # le jeton voyage dans un en-tête, pas dans un cookie
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "Authorization"],
)


# Les routes qui déclenchent un appel au modèle ont un quota propre, plus
# strict : ce sont elles qui coûtent de l'argent à chaque requête.
ROUTES_MODELE = (
    "/api/orientation/conversation",
    "/api/orientation/roadmap",
    "/api/chatbot/conversation",
    "/api/chatbot/entretien/question",
    "/api/chatbot/entretien/evaluation",
)


class Quotas(BaseHTTPMiddleware):
    """Limite les appels par visiteur, sans conserver d'adresse.

    L'adresse n'est utilisée que le temps d'en calculer une empreinte
    tronquée et salée, gardée dans une fenêtre glissante en mémoire qui
    expire d'elle-même. Elle n'est ni stockée, ni journalisée.
    """

    async def dispatch(self, request: Request, call_next):
        chemin = request.url.path

        # Le diagnostic doit rester joignable même quand un visiteur est
        # limité : c'est ce qu'on regarde en premier quand ça coince.
        if (
            request.method == "OPTIONS"
            or chemin in ("/", "/api/sante", "/api/metriques")
            # Les webhooks de paiement viennent du fournisseur, pas d'un
            # visiteur : les compter dans son quota le ferait rejouer en vain.
            or chemin.startswith("/api/paiements/webhook/")
        ):
            return await call_next(request)

        adresse = request.client.host if request.client else "inconnu"
        # Derrière un proxy d'hébergeur, l'adresse réelle est dans l'en-tête.
        transmise = request.headers.get("x-forwarded-for")
        if transmise:
            adresse = transmise.split(",")[0].strip()

        autorise, attente, motif = quotas.verifier(
            adresse, cout_modele=chemin in ROUTES_MODELE
        )
        if not autorise:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Doucement — {motif}. Réessaie dans {attente} secondes."},
                headers={"Retry-After": str(attente)},
            )

        compteurs.incrementer("requetes")
        return await call_next(request)


class EntetesSecurite(BaseHTTPMiddleware):
    """Pose les en-têtes de sécurité et interdit toute mise en cache.

    Une réponse peut contenir des éléments du projet de l'étudiant. Elle ne
    doit être conservée ni par le navigateur, ni par un intermédiaire réseau.
    """

    async def dispatch(self, request, call_next):
        reponse = await call_next(request)
        reponse.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        reponse.headers["Pragma"] = "no-cache"
        reponse.headers["X-Content-Type-Options"] = "nosniff"
        reponse.headers["X-Frame-Options"] = "DENY"
        reponse.headers["Referrer-Policy"] = "no-referrer"
        return reponse


# L'ordre compte : le dernier ajouté s'exécute en premier. Les quotas passent
# donc avant tout le reste, pour qu'une rafale coûte le moins possible.
app.add_middleware(EntetesSecurite)
app.add_middleware(Quotas)

app.include_router(orientation.router)
app.include_router(chatbot.router)
app.include_router(comptes.router)
app.include_router(paiements.router)
app.include_router(synchronisation.router)
app.include_router(rncp.router)
app.include_router(systeme.router)


@app.get("/", include_in_schema=False)
def racine() -> dict:
    return {
        "application": "One Moov",
        "version": "3.0.0",
        "documentation": "/api/docs",
        "diagnostic": "/api/sante",
    }
