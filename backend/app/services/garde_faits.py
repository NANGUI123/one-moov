"""Garde-fou : un montant ou un délai ne sort jamais d'un modèle.

Le principe du produit tient en une phrase — le modèle propose, la donnée
fait autorité. Jusqu'ici cette phrase vivait dans les consignes système des
agents, c'est-à-dire dans une demande polie adressée au modèle. Un modèle
obéit souvent. Souvent ne suffit pas quand une famille engage l'équivalent
d'un mois de revenu sur la foi d'un montant affiché.

Ce module transforme la demande en contrôle.

Comment il décide
-----------------
Il ne cherche pas à savoir si un chiffre est vrai : c'est impossible sans
une base de vérité, et c'est précisément le rôle du module `faits`. Il
vérifie une propriété plus faible et beaucoup plus utile : *tout nombre
chiffré présenté comme un montant ou un délai dans la réponse doit déjà
figurer dans ce qu'on a fourni au modèle*. Un nombre qui apparaît sans être
entré est, par construction, inventé.

Le contexte autorisé réunit deux sources :

  - les faits vérifiés transmis dans l'invite, qui viennent de la base ;
  - le message de l'étudiant lui-même, parce qu'un agent a le droit de
    reprendre « tu dis avoir 800 € par mois » sans que ce soit une
    invention.

Ce qu'il ne couvre pas, et pourquoi c'est dit ici
------------------------------------------------
Les nombres écrits en lettres (« quinze jours ») passent au travers. Les
détecter demanderait un analyseur de langue, pour un gain faible : un modèle
qui invente un montant l'écrit en chiffres, parce que c'est ainsi que les
montants s'écrivent dans les documents dont il a appris. Nous préférons un
contrôle étroit qui ne produit pas de faux positifs plutôt qu'un contrôle
large qui bloquerait des réponses correctes et finirait désactivé.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Unités qui transforment un nombre en engagement. Un nombre nu — « étape 3 »,
# « 2 écoles » — n'intéresse pas ce garde-fou.
_MONNAIES = r"(?:€|EUR|euros?|FCFA|F\s?CFA|XAF|XOF|francs?)"
_DUREES = r"(?:jours?|semaines?|mois|ans?|années?|heures?)"

# Un montant : le nombre précède ou suit son unité monétaire.
_MOTIF_MONTANT = re.compile(
    rf"(?:(?P<avant>\d[\d\s .,]*)\s*{_MONNAIES}"
    rf"|{_MONNAIES}\s*(?P<apres>\d[\d\s .,]*))",
    re.IGNORECASE,
)

# Un délai : le nombre précède son unité de temps.
_MOTIF_DUREE = re.compile(rf"(?P<n>\d[\d\s .,]*)\s*{_DUREES}", re.IGNORECASE)

# Un pourcentage engage autant qu'un montant : un taux d'insertion inventé
# vend une formation.
_MOTIF_TAUX = re.compile(r"(?P<n>\d[\d\s .,]*)\s*%")

# Tout nombre, pour construire l'ensemble autorisé à partir du contexte.
_MOTIF_NOMBRE = re.compile(r"\d[\d\s .,]*")


@dataclass(frozen=True)
class Violation:
    """Un chiffre engageant qui n'était pas dans le contexte fourni."""

    valeur: str          # la forme normalisée, pour comparer
    extrait: str         # le texte tel qu'il apparaît, pour le journal
    nature: str          # montant | duree | taux

    def __str__(self) -> str:  # pragma: no cover - confort de lecture
        return f"{self.nature} « {self.extrait} » absent des faits fournis"


def _normaliser(brut: str) -> str:
    """Ramène « 1 234,50 », « 1.234,50 » et « 1234.5 » à une même clé.

    Les séparateurs de milliers varient d'un document à l'autre et d'un
    modèle à l'autre. Comparer des chaînes brutes ferait passer pour inventé
    un montant correctement repris sous une autre typographie.
    """
    t = unicodedata.normalize("NFKC", brut).strip()
    t = t.replace(" ", "").replace(" ", "").replace(" ", "")
    # Le dernier séparateur rencontré est décimal s'il est suivi de 1 ou 2
    # chiffres ; les autres sont des milliers.
    if "," in t and "." in t:
        dernier = max(t.rfind(","), t.rfind("."))
        entier = re.sub(r"[.,]", "", t[:dernier])
        t = entier + "." + t[dernier + 1:]
    elif "," in t:
        t = t.replace(",", ".") if re.search(r",\d{1,2}$", t) else t.replace(",", "")
    elif "." in t:
        if not re.search(r"\.\d{1,2}$", t):
            t = t.replace(".", "")
    try:
        valeur = float(t)
    except ValueError:
        return t
    # 800 et 800.0 doivent se rencontrer.
    return str(int(valeur)) if valeur == int(valeur) else str(valeur)


def valeurs_du_contexte(*textes: str | None) -> set[str]:
    """Tous les nombres présents dans ce qu'on a donné au modèle."""
    autorisees: set[str] = set()
    for texte in textes:
        if not texte:
            continue
        for brut in _MOTIF_NOMBRE.findall(texte):
            autorisees.add(_normaliser(brut))
    return autorisees


def _chiffres_engageants(texte: str) -> list[tuple[str, str, str]]:
    """Les (valeur normalisée, extrait, nature) que la réponse met en jeu."""
    trouves: list[tuple[str, str, str]] = []
    for m in _MOTIF_MONTANT.finditer(texte):
        brut = m.group("avant") or m.group("apres") or ""
        if brut:
            trouves.append((_normaliser(brut), m.group(0).strip(), "montant"))
    for m in _MOTIF_DUREE.finditer(texte):
        trouves.append((_normaliser(m.group("n")), m.group(0).strip(), "duree"))
    for m in _MOTIF_TAUX.finditer(texte):
        trouves.append((_normaliser(m.group("n")), m.group(0).strip(), "taux"))
    return trouves


def verifier(texte: str, *contexte: str | None) -> list[Violation]:
    """Les chiffres engageants de `texte` absents de `contexte`.

    Liste vide : la réponse ne met en jeu que des valeurs qu'on lui a
    fournies. C'est le seul cas où elle peut être affichée telle quelle.
    """
    if not texte:
        return []
    autorisees = valeurs_du_contexte(*contexte)
    violations: list[Violation] = []
    vues: set[tuple[str, str]] = set()
    for valeur, extrait, nature in _chiffres_engageants(texte):
        if valeur in autorisees:
            continue
        if (valeur, nature) in vues:        # un même montant répété = une alerte
            continue
        vues.add((valeur, nature))
        violations.append(Violation(valeur=valeur, extrait=extrait, nature=nature))
    return violations


def filtrer(texte: str, *contexte: str | None, endpoint: str = "") -> tuple[str, list[Violation]]:
    """Rend le texte si rien n'est inventé, sinon une réponse de repli.

    On ne retouche pas la phrase fautive pour la rendre présentable : une
    réponse dont un chiffre a été retiré reste une réponse construite autour
    de ce chiffre, et elle induit autant en erreur. On la remplace, et on
    renvoie l'étudiant vers la source officielle.
    """
    violations = verifier(texte, *contexte)
    if not violations:
        return texte, []

    logger.warning(
        "Garde-faits : %d valeur(s) inventée(s) sur %s — %s",
        len(violations), endpoint or "?",
        " ; ".join(str(v) for v in violations),
    )
    return (
        "Je préfère ne pas répondre de mémoire sur ce point : le montant ou le "
        "délai que j'allais citer ne figure pas dans nos données vérifiées. "
        "Vérifie-le sur la source officielle de l'étape concernée, elle est "
        "liée dans ta feuille de route."
    ), violations
