"""Quotas et anti-abus.

Le risque est concret : les appels au modèle sont payants, et l'application
est publique et sans compte obligatoire. Un robot qui boucle sur
/api/orientation/conversation vide le crédit en quelques minutes.

Comment on compte sans conserver d'identité
-------------------------------------------
On ne stocke jamais l'adresse IP. On en stocke une empreinte tronquée,
salée par un secret de déploiement, dans une fenêtre glissante en mémoire
qui expire toute seule. L'empreinte ne permet pas de retrouver l'adresse,
et ne survit ni au redémarrage ni à la fenêtre.

Le sel est tiré au hasard au démarrage s'il n'est pas configuré : deux
déploiements ne produisent alors pas les mêmes empreintes, et rien ne se
recoupe d'une instance à l'autre.

Limite assumée : en mémoire, donc par instance. Avec plusieurs instances,
la limite effective est multipliée par leur nombre. Le passage à l'échelle
suppose un Redis partagé — c'est écrit dans les perspectives.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque

from app.config import settings
from app.services.metriques import compteurs

_SEL = settings.sel_quotas or secrets.token_hex(16)


def empreinte(adresse: str) -> str:
    """Empreinte courte et non réversible d'une adresse."""
    brut = hashlib.sha256(f"{_SEL}:{adresse}".encode()).hexdigest()
    return brut[:16]


class FenetreGlissante:
    """Compte les appels par empreinte sur une fenêtre de temps."""

    def __init__(self, limite: int, fenetre_s: int) -> None:
        self.limite = limite
        self.fenetre_s = fenetre_s
        self._verrou = threading.Lock()
        self._appels: dict[str, deque[float]] = defaultdict(deque)
        self._dernier_nettoyage = time.monotonic()

    def autoriser(self, cle: str) -> tuple[bool, int]:
        """Renvoie (autorisé, secondes avant de réessayer)."""
        maintenant = time.monotonic()
        limite_basse = maintenant - self.fenetre_s

        with self._verrou:
            self._nettoyer(maintenant)
            appels = self._appels[cle]
            while appels and appels[0] < limite_basse:
                appels.popleft()

            if len(appels) >= self.limite:
                attente = int(appels[0] + self.fenetre_s - maintenant) + 1
                return False, max(attente, 1)

            appels.append(maintenant)
            return True, 0

    def _nettoyer(self, maintenant: float) -> None:
        """Purge les empreintes inactives. Appelé sous verrou."""
        if maintenant - self._dernier_nettoyage < 60:
            return
        self._dernier_nettoyage = maintenant
        limite_basse = maintenant - self.fenetre_s
        mortes = [c for c, a in self._appels.items() if not a or a[-1] < limite_basse]
        for c in mortes:
            del self._appels[c]


# Deux fenêtres : une courte contre les rafales, une longue contre le
# pompage lent. Les appels au modèle ont leur propre limite, plus stricte,
# parce que ce sont eux qui coûtent.
rafale = FenetreGlissante(settings.quota_rafale, 60)
horaire = FenetreGlissante(settings.quota_horaire, 3600)
modele = FenetreGlissante(settings.quota_modele_horaire, 3600)


def verifier(adresse: str, cout_modele: bool) -> tuple[bool, int, str]:
    """Vérifie les quotas. Renvoie (autorisé, attente, motif)."""
    cle = empreinte(adresse)

    ok, attente = rafale.autoriser(cle)
    if not ok:
        compteurs.incrementer("quota.refus.rafale")
        return False, attente, "trop d'appels en peu de temps"

    ok, attente = horaire.autoriser(cle)
    if not ok:
        compteurs.incrementer("quota.refus.horaire")
        return False, attente, "quota horaire atteint"

    if cout_modele:
        ok, attente = modele.autoriser(cle)
        if not ok:
            compteurs.incrementer("quota.refus.modele")
            return False, attente, "quota horaire d'appels à l'IA atteint"

    return True, 0, ""
