"""Découpage (chunking) déterministe des documents du RAG.

Le corpus peut déjà être organisé en sections, mais une section longue ne
doit pas devenir un seul vecteur. Ce module découpe donc chaque section en
chunks de taille contrôlée avec un chevauchement afin de conserver le contexte
entre deux morceaux.

Aucune dépendance externe n'est nécessaire : on travaille en caractères et
on estime le nombre de tokens pour la traçabilité.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    texte: str
    index: int
    token_count: int


def _normaliser(texte: str) -> str:
    return re.sub(r"\s+", " ", (texte or "")).strip()


def _estimer_tokens(texte: str) -> int:
    # Estimation volontairement simple : utile pour les métriques, pas pour
    # facturer l'API. Le provider reste la source de vérité sur les tokens.
    return max(1, round(len(texte) / 4)) if texte else 0


def _couper_a_borne(texte: str, borne: int) -> tuple[str, str]:
    """Coupe au dernier espace avant la borne, sans couper un mot."""
    if len(texte) <= borne:
        return texte, ""
    pos = texte.rfind(" ", 0, borne + 1)
    if pos < int(borne * 0.55):
        pos = borne
    return texte[:pos].rstrip(), texte[pos:].lstrip()


def chunker(
    texte: str,
    taille_cible: int = 1200,
    chevauchement: int = 180,
) -> list[Chunk]:
    """Transforme un texte en chunks avec overlap.

    Les phrases sont conservées autant que possible. Pour un passage court,
    un seul chunk est produit.
    """
    texte = _normaliser(texte)
    if not texte:
        return []
    if taille_cible <= 0 or chevauchement < 0 or chevauchement >= taille_cible:
        raise ValueError("taille_cible > chevauchement >= 0 est requis")

    phrases = re.split(r"(?<=[.!?])\s+", texte)
    morceaux: list[str] = []
    courant = ""

    for phrase in phrases:
        phrase = phrase.strip()
        if not phrase:
            continue

        if len(phrase) > taille_cible:
            if courant:
                morceaux.append(courant)
                courant = ""
            reste = phrase
            while len(reste) > taille_cible:
                morceau, reste = _couper_a_borne(reste, taille_cible)
                morceaux.append(morceau)
                # Le chevauchement sera appliqué lors de l'assemblage suivant.
                reste = reste.lstrip()
            if reste:
                courant = reste
            continue

        candidat = f"{courant} {phrase}".strip()
        if len(candidat) <= taille_cible:
            courant = candidat
        else:
            if courant:
                morceaux.append(courant)
            courant = phrase

    if courant:
        morceaux.append(courant)

    # Ajout d'overlap à partir de la fin du chunk précédent.
    resultats: list[Chunk] = []
    precedent = ""
    for index, morceau in enumerate(morceaux):
        if index > 0 and chevauchement:
            overlap = precedent[-chevauchement:].lstrip()
            morceau = f"{overlap} {morceau}".strip()
            # Si l'overlap pousse le chunk au-delà de la cible, on garde le
            # contenu principal et seulement l'overlap réellement utile.
            if len(morceau) > taille_cible + chevauchement:
                morceau = morceau[-(taille_cible + chevauchement):].lstrip()
        resultats.append(
            Chunk(texte=morceau, index=index, token_count=_estimer_tokens(morceau))
        )
        precedent = morceaux[index]

    return resultats
