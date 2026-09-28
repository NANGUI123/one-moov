"""Mesure la qualité de la recherche, contre une référence.

    python -m scripts.evaluer

Pourquoi ce script existe
-------------------------
Dire « notre RAG fonctionne » ne veut rien dire. Un résultat sans référence
de comparaison n'est pas un résultat. Ce script compare donc trois façons de
construire la requête lexicale sur le même jeu de questions, et montre ce
que chaque décision d'ingénierie a réellement apporté.

Les trois méthodes comparées
----------------------------
    1. ET      plainto_tsquery, la construction par défaut de PostgreSQL.
               Tous les mots de la question doivent figurer dans le passage.
               C'est la référence : ce qu'on aurait eu sans y réfléchir.

    2. OU      notre fonction requete_ou : la question est découpée en
               lexèmes reliés par OU, et le classement par ts_rank_cd fait
               remonter les passages qui couvrent le plus de termes.

    3. OU + phase   la même chose, avec le filtre de phase déduit de la
               question par l'agent. C'est ce qui tourne en production.

Marge d'erreur, fixée AVANT de mesurer
--------------------------------------
30 questions, c'est peu. L'intervalle de confiance de Wilson à 95 % est
calculé et affiché pour chaque taux : sur n = 30, un rappel mesuré à 90 %
tient dans un intervalle d'environ [74 %, 97 %]. Deux méthodes dont les
intervalles se recouvrent ne sont pas départagées par cette mesure, et le
script le dit.

Seuil retenu à l'avance : nous considérons l'écart entre deux méthodes comme
établi seulement si leurs intervalles de confiance à 95 % ne se recouvrent
pas.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.agents.agent2.chatbot import _deviner_phase  # noqa: E402
from app.db import SessionLocal  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent
JEU = RACINE / "app" / "donnees" / "evaluation.json"

K_PRINCIPAL = 3   # l'agent envoie les 3 premiers passages au modèle


def wilson(reussites: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de confiance de Wilson, adapté aux petits effectifs.

    L'intervalle normal donnerait des bornes absurdes (au-dessus de 100 %)
    sur n = 30 avec un taux élevé. Wilson reste dans [0, 1].
    """
    if total == 0:
        return (0.0, 0.0)
    p = reussites / total
    denominateur = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denominateur
    ecart = z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denominateur
    return (max(0.0, centre - ecart), min(1.0, centre + ecart))


def rechercher(db, methode: str, question: str, phase: str | None, limite: int) -> list[int]:
    """Renvoie les identifiants des passages trouvés, dans l'ordre."""
    if methode == "et":
        # La référence : plainto_tsquery relie tous les mots par ET.
        requete = text(
            """
            SELECT p.id
            FROM passage p
            JOIN document_source d ON d.id = p.document_id
            WHERE d.actif AND p.fts @@ plainto_tsquery('french', :q)
            ORDER BY ts_rank_cd(p.fts, plainto_tsquery('french', :q)) DESC
            LIMIT :k
            """
        )
        params = {"q": question, "k": limite}

    elif methode == "ou":
        requete = text(
            """
            SELECT p.id
            FROM passage p
            JOIN document_source d ON d.id = p.document_id
            WHERE d.actif AND requete_ou(:q) IS NOT NULL AND p.fts @@ requete_ou(:q)
            ORDER BY ts_rank_cd(p.fts, requete_ou(:q)) DESC
            LIMIT :k
            """
        )
        params = {"q": question, "k": limite}

    else:  # ou + phase
        requete = text(
            """
            SELECT p.id
            FROM passage p
            JOIN document_source d ON d.id = p.document_id
            WHERE d.actif AND requete_ou(:q) IS NOT NULL AND p.fts @@ requete_ou(:q)
              AND (:phase IS NULL OR p.phase = :phase)
            ORDER BY ts_rank_cd(p.fts, requete_ou(:q)) DESC
            LIMIT :k
            """
        )
        params = {"q": question, "k": limite, "phase": phase}

    return [ligne[0] for ligne in db.execute(requete, params).fetchall()]


def main() -> None:
    jeu = json.loads(JEU.read_text(encoding="utf-8"))
    questions = jeu["questions"]
    db = SessionLocal()

    print(f"\nJeu d'évaluation : {len(questions)} questions, corpus de "
          f"{db.execute(text('SELECT count(*) FROM passage')).scalar()} passages.")
    print(f"Mesure principale : rappel à {K_PRINCIPAL}. "
          "Intervalle de confiance de Wilson à 95 %.\n")

    methodes = [
        ("et", "ET (plainto_tsquery) — la référence"),
        ("ou", "OU (requete_ou)"),
        ("ou_phase", "OU + filtre de phase — la production"),
    ]

    resultats: dict[str, dict] = {}

    for cle, libelle in methodes:
        a_1 = a_k = 0
        echecs = []

        for item in questions:
            phase = _deviner_phase(item["question"], None) if cle == "ou_phase" else None
            trouves = rechercher(db, cle, item["question"], phase, K_PRINCIPAL)
            attendu = item["passage_attendu"]

            if trouves and trouves[0] == attendu:
                a_1 += 1
            if attendu in trouves:
                a_k += 1
            else:
                echecs.append((item["question"], attendu, trouves, phase))

        n = len(questions)
        bas, haut = wilson(a_k, n)
        resultats[cle] = {
            "libelle": libelle, "a_1": a_1, "a_k": a_k, "n": n,
            "bas": bas, "haut": haut, "echecs": echecs,
        }

        print(f"  {libelle}")
        print(f"    rappel à 1 : {a_1}/{n}  ({a_1/n:.0%})")
        print(f"    rappel à {K_PRINCIPAL} : {a_k}/{n}  ({a_k/n:.0%})"
              f"   IC 95 % [{bas:.0%}, {haut:.0%}]\n")

    # --- Les écarts sont-ils établis ? ---
    print("Comparaisons")
    reference = resultats["et"]
    for cle in ("ou", "ou_phase"):
        courant = resultats[cle]
        gain = (courant["a_k"] - reference["a_k"]) / reference["n"]
        # Deux intervalles qui se recouvrent ne départagent pas les méthodes.
        etabli = courant["bas"] > reference["haut"]
        verdict = "écart établi" if etabli else "écart NON établi sur cet effectif"
        print(f"  {courant['libelle']} contre la référence : "
              f"{gain:+.0%} de rappel — {verdict}")

    # --- Ce qui échoue encore ---
    production = resultats["ou_phase"]
    print(f"\nCe qui échoue encore en production : "
          f"{len(production['echecs'])} question(s) sur {production['n']}")
    for question, attendu, trouves, phase in production["echecs"]:
        libelle = db.execute(
            text("SELECT titre FROM passage WHERE id = :i"), {"i": attendu}
        ).scalar()
        print(f"\n  « {question} »")
        print(f"    attendu  : [{attendu}] {libelle}")
        print(f"    phase devinée : {phase or '(aucune)'}")
        if trouves:
            titres = db.execute(
                text("SELECT id, titre FROM passage WHERE id = ANY(:ids)"),
                {"ids": trouves},
            ).fetchall()
            ordre = {i: t for i, t in titres}
            print("    trouvé   : " + " | ".join(
                f"[{i}] {ordre.get(i, '?')}" for i in trouves))
        else:
            print("    trouvé   : rien")

    print(
        "\nLimites de cette mesure\n"
        f"  - {production['n']} questions écrites par l'équipe, non collectées\n"
        "    auprès d'étudiants réels : un biais de formulation subsiste.\n"
        "  - Un seul passage attendu par question, alors que plusieurs peuvent\n"
        "    être pertinents. La mesure est donc pessimiste.\n"
        "  - Corpus de 30 passages. Ces taux ne se transposent pas à un corpus\n"
        "    de plusieurs milliers, où la discrimination devient plus difficile.\n"
        "  - Les embeddings sont désactivés : seule la voie lexicale est mesurée.\n"
    )

    db.close()


if __name__ == "__main__":
    main()
