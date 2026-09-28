"""Comptes : inscription, vérification, connexion, sauvegarde, suppression.

Le compte sert à une seule chose : retrouver son projet et sa feuille de
route depuis un autre téléphone, ou après avoir fermé l'application. Il ne
sert ni à profiler, ni à recontacter, ni à mesurer.

Trois règles tenues ici :

  - Aucune conversation n'est enregistrée. Ni l'orientation, ni le chatbot.
    Les échanges restent dans le navigateur de l'étudiant.
  - Les réponses ne disent jamais si une adresse existe. « Connexion
    impossible » couvre les deux cas, sinon l'API devient un annuaire de
    comptes.
  - La suppression efface vraiment, tout de suite, sans corbeille.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.services import courriel, securite
from app.services.metriques import compteurs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/comptes", tags=["Comptes"])

MAX_TENTATIVES_CODE = 5

PAYS_RESIDENCE = {"Cameroun", "Congo-Brazzaville"}


# --------------------------------------------------------------- contrats


class Inscription(BaseModel):
    email: EmailStr
    mot_de_passe: str = Field(min_length=10, max_length=200)
    pays: str = Field(min_length=2, max_length=80)


class Connexion(BaseModel):
    email: EmailStr
    mot_de_passe: str = Field(min_length=1, max_length=200)


class Verification(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


class DemandeCode(BaseModel):
    email: EmailStr


class Sauvegarde(BaseModel):
    """Ce qu'un compte peut enregistrer. Rien de plus n'est accepté."""

    profil: dict[str, Any] | None = None
    roadmap: dict[str, Any] | None = None
    # None, et non une liste vide par défaut : les étapes cochées appartiennent
    # à la file de synchronisation, qui les arbitre étape par étape avec un
    # horodatage. Une sauvegarde qui enverrait la liste entière écraserait cet
    # arbitrage et défairait une action venue d'un autre appareil. Le champ
    # reste accepté pour les clients qui le fournissent encore.
    etapes_faites: list[int] | None = None
    secteurs_payes: list[str] = Field(default_factory=list)
    chatbot_ouvert: bool = False


class Suppression(BaseModel):
    """La suppression est irréversible : on redemande le mot de passe."""

    mot_de_passe: str = Field(min_length=1, max_length=200)


# ------------------------------------------------------------ dépendances


def utilisateur_courant(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> dict:
    """Résout le compte porté par le jeton, ou refuse."""
    refus = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session expirée. Reconnecte-toi.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not authorization or not authorization.lower().startswith("bearer "):
        raise refus

    identifiant = securite.lire_jeton(authorization[7:].strip())
    if not identifiant:
        raise refus

    ligne = db.execute(
        text("SELECT id, email, email_verifie FROM utilisateur WHERE id = :i"),
        {"i": identifiant},
    ).fetchone()
    if not ligne:
        # Compte supprimé alors que le jeton court encore : le jeton ne vaut
        # plus rien, mais rien ne casse.
        raise refus

    db.execute(
        text("UPDATE utilisateur SET derniere_activite = now() WHERE id = :i"),
        {"i": identifiant},
    )
    db.commit()

    return {"id": str(ligne[0]), "email": ligne[1], "email_verifie": ligne[2]}


def utilisateur_optionnel(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> dict | None:
    """Comme utilisateur_courant, mais sans refuser l'anonyme.

    Le paiement doit rester possible sans compte : un étudiant peut très
    bien utiliser One Moov sans en créer un, et il paie quand même.
    """
    if not authorization:
        return None
    try:
        return utilisateur_courant(authorization, db)
    except HTTPException:
        return None


# ---------------------------------------------------------------- helpers


def _emettre_code(db: Session, utilisateur_id: str, email: str) -> bool:
    """Crée un code, l'envoie, et invalide les précédents."""
    code = securite.generer_code()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.verification_duree_minutes
    )

    db.execute(
        text(
            "UPDATE code_verification SET utilise_le = now() "
            "WHERE utilisateur_id = :u AND utilise_le IS NULL"
        ),
        {"u": utilisateur_id},
    )
    db.execute(
        text(
            "INSERT INTO code_verification (utilisateur_id, code_empreinte, expire_le) "
            "VALUES (:u, :c, :e)"
        ),
        {"u": utilisateur_id, "c": securite.hacher_code(code), "e": expire},
    )
    db.commit()

    return courriel.envoyer_code(email, code)


def _mot_de_passe_acceptable(mot_de_passe: str) -> str | None:
    """Renvoie le motif du refus, ou None si le mot de passe convient.

    Une longueur minimale plutôt qu'un jeu de caractères imposé : une phrase
    longue résiste mieux qu'un « Passw0rd! » que tout le monde compose de la
    même façon quand on exige une majuscule et un chiffre.
    """
    if len(mot_de_passe) < 10:
        return "Choisis un mot de passe d'au moins 10 caractères."
    if re.fullmatch(r"(.)\1*", mot_de_passe):
        return "Ce mot de passe est trop simple."
    return None


# ------------------------------------------------------------------ routes


@router.post("/inscription", status_code=status.HTTP_201_CREATED)
def inscription(corps: Inscription, db: Session = Depends(get_db)) -> dict:
    if corps.pays not in PAYS_RESIDENCE:
        raise HTTPException(422, "Choisis un pays de résidence pris en charge.")

    motif = _mot_de_passe_acceptable(corps.mot_de_passe)
    if motif:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, motif)

    email = corps.email.lower()
    existe = db.execute(
        text("SELECT id, email_verifie FROM utilisateur WHERE email = :e"), {"e": email}
    ).fetchone()

    if existe:
        # On ne révèle pas que l'adresse est déjà prise. Si le compte n'est
        # pas encore vérifié, on renvoie simplement un nouveau code : c'est
        # le cas d'un étudiant qui a perdu le premier.
        if not existe[1]:
            db.execute(
                text("UPDATE utilisateur SET pays_residence = :p WHERE id = :i"),
                {"p": corps.pays, "i": str(existe[0])},
            )
            db.commit()
            _emettre_code(db, str(existe[0]), email)
        compteurs.incrementer("comptes.inscription.doublon")
        return {
            "statut": "verification_requise",
            "message": "Si cette adresse peut être utilisée, un code vient d'être envoyé.",
            "envoi_reel": courriel.smtp_configure(),
        }

    identifiant = db.execute(
        text(
            "INSERT INTO utilisateur (email, mot_de_passe, pays_residence) "
            "VALUES (:e, :m, :p) RETURNING id"
        ),
        {
            "e": email,
            "m": securite.hacher_mot_de_passe(corps.mot_de_passe),
            "p": corps.pays,
        },
    ).scalar()
    db.commit()

    _emettre_code(db, str(identifiant), email)
    compteurs.incrementer("comptes.inscription")

    return {
        "statut": "verification_requise",
        "message": "Si cette adresse peut être utilisée, un code vient d'être envoyé.",
        "envoi_reel": courriel.smtp_configure(),
    }


@router.post("/code")
def renvoyer_code(corps: DemandeCode, db: Session = Depends(get_db)) -> dict:
    """Renvoie un code. Répond pareil que l'adresse existe ou non."""
    ligne = db.execute(
        text("SELECT id, email_verifie FROM utilisateur WHERE email = :e"),
        {"e": corps.email.lower()},
    ).fetchone()

    if ligne and not ligne[1]:
        _emettre_code(db, str(ligne[0]), corps.email.lower())

    return {
        "statut": "envoye",
        "message": "Si cette adresse attend une vérification, un code vient d'être envoyé.",
        "envoi_reel": courriel.smtp_configure(),
    }


@router.post("/verification")
def verification(corps: Verification, db: Session = Depends(get_db)) -> dict:
    """Valide l'adresse et ouvre la session."""
    refus = HTTPException(status.HTTP_400_BAD_REQUEST, "Code invalide ou expiré.")

    ligne = db.execute(
        text("SELECT id, email_verifie FROM utilisateur WHERE email = :e"),
        {"e": corps.email.lower()},
    ).fetchone()
    if not ligne:
        raise refus

    utilisateur_id = str(ligne[0])

    code = db.execute(
        text(
            "SELECT id, code_empreinte, tentatives FROM code_verification "
            "WHERE utilisateur_id = :u AND utilise_le IS NULL AND expire_le > now() "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"u": utilisateur_id},
    ).fetchone()
    if not code:
        raise refus

    # Un code à six chiffres se devine en un million d'essais. On plafonne.
    if code[2] >= MAX_TENTATIVES_CODE:
        db.execute(
            text("UPDATE code_verification SET utilise_le = now() WHERE id = :i"),
            {"i": code[0]},
        )
        db.commit()
        compteurs.incrementer("comptes.verification.epuisee")
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Trop de tentatives. Demande un nouveau code.",
        )

    if not securite.codes_egaux(securite.hacher_code(corps.code), code[1]):
        db.execute(
            text("UPDATE code_verification SET tentatives = tentatives + 1 WHERE id = :i"),
            {"i": code[0]},
        )
        db.commit()
        compteurs.incrementer("comptes.verification.echec")
        raise refus

    db.execute(
        text("UPDATE code_verification SET utilise_le = now() WHERE id = :i"),
        {"i": code[0]},
    )
    db.execute(
        text("UPDATE utilisateur SET email_verifie = TRUE WHERE id = :i"),
        {"i": utilisateur_id},
    )
    db.commit()
    compteurs.incrementer("comptes.verification.succes")

    jeton, duree = securite.creer_jeton(utilisateur_id)
    return {
        "jeton": jeton,
        "duree_secondes": duree,
        "compte": {
            "email": corps.email.lower(),
            "email_verifie": True,
            "pays_residence": db.execute(
                text("SELECT pays_residence FROM utilisateur WHERE id = :i"),
                {"i": utilisateur_id},
            ).scalar(),
        },
    }


@router.post("/connexion")
def connexion(corps: Connexion, db: Session = Depends(get_db)) -> dict:
    refus = HTTPException(status.HTTP_401_UNAUTHORIZED, "Connexion impossible.")

    ligne = db.execute(
        text("SELECT id, mot_de_passe, email_verifie, pays_residence FROM utilisateur WHERE email = :e"),
        {"e": corps.email.lower()},
    ).fetchone()

    if not ligne:
        # On hache quand même : sans cela, la durée de la réponse indiquerait
        # si l'adresse existe.
        securite.hacher_mot_de_passe(corps.mot_de_passe)
        compteurs.incrementer("comptes.connexion.echec")
        raise refus

    if not securite.verifier_mot_de_passe(corps.mot_de_passe, ligne[1]):
        compteurs.incrementer("comptes.connexion.echec")
        raise refus

    if not ligne[2]:
        _emettre_code(db, str(ligne[0]), corps.email.lower())
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Adresse non vérifiée. Un nouveau code vient d'être envoyé.",
        )

    compteurs.incrementer("comptes.connexion.succes")
    jeton, duree = securite.creer_jeton(str(ligne[0]))
    return {
        "jeton": jeton,
        "duree_secondes": duree,
        "compte": {
            "email": corps.email.lower(),
            "email_verifie": True,
            "pays_residence": ligne[3],
        },
    }


@router.get("/moi")
def moi(compte: dict = Depends(utilisateur_courant), db: Session = Depends(get_db)) -> dict:
    """Le compte et ce qu'il a enregistré."""
    orientation = db.execute(
        text("SELECT profil FROM orientation_enregistree WHERE utilisateur_id = :u"),
        {"u": compte["id"]},
    ).fetchone()

    roadmap = db.execute(
        text(
            "SELECT contenu, etapes_faites, secteurs_payes, chatbot_ouvert "
            "FROM roadmap_enregistree WHERE utilisateur_id = :u"
        ),
        {"u": compte["id"]},
    ).fetchone()

    return {
        "compte": {
            "email": compte["email"],
            "email_verifie": compte["email_verifie"],
            "pays_residence": db.execute(
                text("SELECT pays_residence FROM utilisateur WHERE id = :u"),
                {"u": compte["id"]},
            ).scalar(),
        },
        "profil": orientation[0] if orientation else None,
        "roadmap": roadmap[0] if roadmap else None,
        "etapes_faites": list(roadmap[1]) if roadmap else [],
        "secteurs_payes": list(roadmap[2]) if roadmap else [],
        "chatbot_ouvert": roadmap[3] if roadmap else False,
    }


@router.put("/sauvegarde")
def sauvegarder(
    corps: Sauvegarde,
    compte: dict = Depends(utilisateur_courant),
    db: Session = Depends(get_db),
) -> dict:
    """Enregistre le projet et la feuille de route. Jamais les conversations."""
    if corps.profil is not None:
        db.execute(
            text(
                # maj_horodatage suit maj_le : une seule horloge fait autorité
                # sur la fraîcheur du profil, sinon une action hors ligne
                # ancienne pourrait gagner contre une sauvegarde récente.
                "INSERT INTO orientation_enregistree (utilisateur_id, profil, maj_horodatage) "
                "VALUES (:u, CAST(:p AS jsonb), now()) "
                "ON CONFLICT (utilisateur_id) DO UPDATE "
                "SET profil = EXCLUDED.profil, maj_horodatage = now(), maj_le = now()"
            ),
            {"u": compte["id"], "p": _json(corps.profil)},
        )

    if corps.roadmap is not None:
        db.execute(
            text(
                "INSERT INTO roadmap_enregistree "
                "  (utilisateur_id, contenu, etapes_faites, secteurs_payes, chatbot_ouvert) "
                "VALUES (:u, CAST(:c AS jsonb), :e, :s, :b) "
                "ON CONFLICT (utilisateur_id) DO UPDATE SET "
                "  contenu = EXCLUDED.contenu, "
                # Les étapes ne sont touchées que si le client les fournit.
                "  etapes_faites = CASE WHEN :maj_etapes THEN EXCLUDED.etapes_faites "
                "                       ELSE roadmap_enregistree.etapes_faites END, "
                "  secteurs_payes = EXCLUDED.secteurs_payes, "
                "  chatbot_ouvert = EXCLUDED.chatbot_ouvert, maj_le = now()"
            ),
            {
                "u": compte["id"], "c": _json(corps.roadmap),
                "e": corps.etapes_faites or [],
                "maj_etapes": corps.etapes_faites is not None,
                "s": corps.secteurs_payes,
                "b": corps.chatbot_ouvert,
            },
        )

    db.commit()
    compteurs.incrementer("comptes.sauvegarde")
    return {"statut": "enregistre"}


@router.post("/suppression")
def supprimer(
    corps: Suppression,
    compte: dict = Depends(utilisateur_courant),
    db: Session = Depends(get_db),
) -> dict:
    """Droit à la suppression : efface le compte et tout ce qui s'y rattache."""
    stocke = db.execute(
        text("SELECT mot_de_passe FROM utilisateur WHERE id = :i"), {"i": compte["id"]}
    ).scalar()

    if not stocke or not securite.verifier_mot_de_passe(corps.mot_de_passe, stocke):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Mot de passe incorrect.")

    # Les tables filles partent en cascade : orientation, feuille de route,
    # codes de vérification. Aucun effacement logique, aucune copie gardée.
    db.execute(text("DELETE FROM utilisateur WHERE id = :i"), {"i": compte["id"]})
    db.commit()
    compteurs.incrementer("comptes.suppression")

    return {"statut": "supprime", "message": "Ton compte et tes données ont été effacés."}


def _json(valeur: Any) -> str:
    import json

    return json.dumps(valeur, ensure_ascii=False)
