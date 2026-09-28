"""Routes de diagnostic et de référentiel."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.services import embeddings, rag as svc_rag, faits as svc_faits
from app.services import courriel
from app.services import notifications as svc_notifications
from app.services import paiement as svc_paiement
from app.services.llm import info_fournisseur
from app.services.metriques import compteurs

router = APIRouter(prefix="/api", tags=["Système"])


@router.get("/sante")
def sante(db: Session = Depends(get_db)) -> dict:
    """État complet du service.

    N'expose jamais de clé d'API. C'est le premier endroit à consulter
    quand quelque chose ne fonctionne pas après un déploiement.
    """
    try:
        db.execute(text("SELECT 1"))
        base_ok = True
    except Exception:  # noqa: BLE001
        base_ok = False

    etat_rag = svc_rag.etat(db) if base_ok else {}

    return {
        "statut": "ok" if base_ok else "degrade",
        "version": "2.0.0",
        "base_de_donnees": "connectee" if base_ok else "injoignable",
        "modele": info_fournisseur(),
        "embeddings": embeddings.info(),
        "paiement": svc_paiement.info(),
        "notifications": svc_notifications.info(),
        # L'état de l'envoi d'e-mails, sans jamais exposer l'identifiant ni le
        # mot de passe. C'est la question qu'on se pose juste après avoir posé
        # les variables SMTP, et y répondre autrement obligeait à créer un
        # compte pour voir si le code arrivait.
        "courriel": {
            "configure": courriel.smtp_configure(),
            "hote": settings.smtp_hote or None,
            "expediteur": settings.smtp_expediteur,
            "sans_smtp": (
                None if courriel.smtp_configure()
                else "les codes de vérification sont écrits dans les journaux"
            ),
        },
        "rag": etat_rag,
        "donnees_conservees": {
            "comptes": "e-mail, empreinte du mot de passe, projet, feuille de route",
            "conversations": "aucune, pour personne",
            "suppression": "immédiate et totale, sur demande du titulaire",
        },
        "horodatage": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/metriques")
def metriques() -> dict:
    """Compteurs d'exploitation, anonymes et en mémoire.

    Sert à répondre à « le service tient-il ? » et « l'orchestrateur
    bascule-t-il vraiment ? ». Aucun compteur n'est indexé par personne :
    ni compte, ni adresse, ni empreinte.
    """
    instantane = compteurs.instantane()
    instantane["orchestrateur"] = info_fournisseur().get("orchestrateur", [])
    return instantane


@router.get("/faits")
def faits(pays: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Les valeurs officielles en vigueur, avec leur source et leur fraîcheur.

    Cet endpoint est public et volontairement lisible : il montre que les
    chiffres affichés dans l'application viennent d'une base sourcée, et non
    d'une génération.
    """
    liste = svc_faits.pour_pays(db, pays)
    return {
        "pays": pays,
        "faits": [f.to_dict() for f in liste],
        "a_reverifier": [f.cle for f in liste if f.a_reverifier],
    }


@router.get("/villes")
def villes(db: Session = Depends(get_db)) -> dict:
    """Le référentiel des villes, avec les coûts et leur date de vérification."""
    lignes = db.execute(
        text(
            """
            SELECT nom, region, cout_vie_mensuel, loyer_moyen_studio,
                   population_etudiante, reseau_diaspora, description, verifie_le
            FROM ville ORDER BY cout_vie_mensuel ASC
            """
        )
    ).fetchall()
    return {
        "villes": [
            {
                "nom": l[0], "region": l[1], "cout_vie_mensuel": int(l[2]),
                "loyer_moyen_studio": int(l[3]), "population_etudiante": l[4],
                "reseau_diaspora": l[5], "description": l[6],
                "verifie_le": l[7].isoformat(),
            }
            for l in lignes
        ]
    }
