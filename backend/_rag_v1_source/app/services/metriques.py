"""Observabilité : compteurs en mémoire.

Volontairement en mémoire, et volontairement anonymes. Ces compteurs
servent à répondre à une question d'exploitation — « le service tient-il ? »,
« l'orchestrateur bascule-t-il vraiment ? » — pas à suivre quelqu'un. Aucun
compteur n'est indexé par utilisateur, par compte ou par adresse.

Conséquence assumée : les compteurs repartent de zéro à chaque redémarrage.
Pour une supervision durable, ils seraient exposés à Prometheus, qui les
échantillonne de l'extérieur.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict


class Compteurs:
    """Compteurs et échantillons de durée, protégés par un verrou."""

    def __init__(self) -> None:
        self._verrou = threading.Lock()
        self._valeurs: dict[str, int] = defaultdict(int)
        self._durees: dict[str, list[float]] = defaultdict(list)
        self._depuis = time.time()

    def incrementer(self, cle: str, de: int = 1) -> None:
        with self._verrou:
            self._valeurs[cle] += de

    def observer(self, cle: str, valeur: float) -> None:
        with self._verrou:
            echantillons = self._durees[cle]
            echantillons.append(valeur)
            # On garde une fenêtre glissante : la mémoire ne doit pas croître
            # indéfiniment sur un service qui tourne des semaines.
            if len(echantillons) > 500:
                del echantillons[:-500]

    def instantane(self) -> dict:
        with self._verrou:
            valeurs = dict(sorted(self._valeurs.items()))
            durees = {
                cle: {
                    "echantillons": len(v),
                    "moyenne_ms": round(sum(v) / len(v)),
                    "max_ms": round(max(v)),
                }
                for cle, v in self._durees.items()
                if v
            }
            depuis = self._depuis

        return {
            "depuis_secondes": round(time.time() - depuis),
            "compteurs": valeurs,
            "durees": durees,
        }

    def reinitialiser(self) -> None:
        with self._verrou:
            self._valeurs.clear()
            self._durees.clear()
            self._depuis = time.time()


compteurs = Compteurs()
