"""Mots de passe, jetons et codes de vérification.

Trois décisions à justifier :

1. scrypt plutôt que bcrypt. scrypt est dans la bibliothèque standard de
   Python, donc aucune dépendance de plus à auditer et à maintenir, et il
   est coûteux en mémoire autant qu'en temps — ce qui rend une attaque par
   GPU nettement moins rentable.

2. Les jetons sont signés, pas chiffrés. Un jeton ne contient que
   l'identifiant du compte et une date d'expiration : rien qui poserait
   problème s'il était lu. Il n'y a ni nom, ni adresse, ni projet dedans.

3. Les codes de vérification sont stockés sous forme d'empreinte, comme les
   mots de passe. Un accès en lecture à la base ne permet donc pas de
   valider un compte à la place de son propriétaire.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

# Paramètres scrypt. n=2^14 tient en ~16 Mo et prend quelques dizaines de
# millisecondes : assez lent pour décourager une attaque par dictionnaire,
# assez rapide pour une connexion.
_N, _R, _P, _LONGUEUR = 2**14, 8, 1, 32


def hacher_mot_de_passe(mot_de_passe: str) -> str:
    sel = secrets.token_bytes(16)
    empreinte = hashlib.scrypt(
        mot_de_passe.encode("utf-8"), salt=sel, n=_N, r=_R, p=_P, dklen=_LONGUEUR
    )
    return "$".join(
        ["scrypt", str(_N), str(_R), str(_P), base64.b64encode(sel).decode(),
         base64.b64encode(empreinte).decode()]
    )


def verifier_mot_de_passe(mot_de_passe: str, stocke: str) -> bool:
    """Comparaison à temps constant, pour ne pas fuiter par la durée."""
    try:
        algo, n, r, p, sel_b64, empreinte_b64 = stocke.split("$")
        if algo != "scrypt":
            return False
        sel = base64.b64decode(sel_b64)
        attendue = base64.b64decode(empreinte_b64)
        calculee = hashlib.scrypt(
            mot_de_passe.encode("utf-8"),
            salt=sel, n=int(n), r=int(r), p=int(p), dklen=len(attendue),
        )
        return hmac.compare_digest(calculee, attendue)
    except (ValueError, TypeError):
        return False


def creer_jeton(utilisateur_id: str) -> tuple[str, int]:
    """Renvoie (jeton, durée de validité en secondes)."""
    duree = timedelta(hours=settings.jwt_duree_heures)
    expire = datetime.now(timezone.utc) + duree
    jeton = jwt.encode(
        {"sub": str(utilisateur_id), "exp": expire, "iss": "one-moov"},
        settings.jwt_secret,
        algorithm="HS256",
    )
    return jeton, int(duree.total_seconds())


def lire_jeton(jeton: str) -> str | None:
    """Renvoie l'identifiant du compte, ou None si le jeton est invalide.

    L'algorithme est imposé à la lecture : sans cela, un jeton forgé avec
    « alg: none » serait accepté.
    """
    try:
        charge = jwt.decode(
            jeton, settings.jwt_secret, algorithms=["HS256"], issuer="one-moov"
        )
    except jwt.InvalidTokenError:
        return None
    return charge.get("sub")


def generer_code() -> str:
    """Code de vérification à six chiffres, tiré cryptographiquement."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hacher_code(code: str) -> str:
    """Empreinte d'un code de vérification, salée par le secret du service."""
    return hashlib.sha256(f"{settings.jwt_secret}:{code}".encode()).hexdigest()


def codes_egaux(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
