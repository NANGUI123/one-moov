"""Mesure la pertinence de la recherche documentaire.

    python -m scripts.evaluer_rag
    python -m scripts.evaluer_rag --phase          # avec filtre de phase
    python -m scripts.evaluer_rag --k 1 --k 3 --k 5

Pourquoi ce script existe
-------------------------
Le jeu d'évaluation (app/donnees/evaluation.json) portait son protocole et ses
limites, mais rien ne le lisait. Un protocole qu'on n'exécute pas ne mesure
rien : il décrit une intention. Dire « notre recherche fonctionne » sans ce
chiffre, c'est exactement le reproche qu'un jury adresse à juste titre.

Ce que le script mesure
-----------------------
Le rappel à k : la part des questions dont le passage attendu figure parmi les
k premiers résultats. La mesure principale est le rappel à 3, parce que c'est
le nombre de passages que l'agent transmet au modèle. Au-delà, la mesure ne
dirait plus rien de l'usage réel.

Pourquoi un intervalle de confiance
-----------------------------------
Sur 30 questions, un rappel de 53 % n'est pas « 53 % ». L'intervalle de Wilson
donne l'étendue des valeurs compatibles avec l'observation. Il est préféré à
l'approximation normale, qui sur de petits effectifs produit des bornes
négatives ou supérieures à 100 % — et qui ferait croire à une précision que
trente questions ne peuvent pas donner.

Deux résultats ne sont tenus pour différents que si leurs intervalles ne se
recouvrent pas. Ce seuil est fixé ici, avant toute mesure, pour qu'il ne soit
pas choisi après coup en fonction du résultat souhaité.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from sqlalchemy import text as sql

from app.db import SessionLocal
from app.services import rag

JEU = Path(__file__).resolve().parent.parent / "app" / "donnees" / "evaluation.json"


def wilson(succes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de Wilson à 95 %, en proportions."""
    if total == 0:
        return (0.0, 0.0)
    p = succes / total
    denom = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denom
    demi = z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denom
    return (max(0.0, centre - demi), min(1.0, centre + demi))


def pct(x: float) -> str:
    return f"{x * 100:.0f} %".replace(".", ",")


def reference(db, requete: str, limite: int) -> list[int]:
    """La référence de comparaison : une recherche plein texte naïve.

    Elle prend la question telle quelle et cherche la chaîne entière dans le
    contenu des passages. C'est ce qu'on obtient sans travail sur la requête,
    et c'est contre ça qu'il faut mesurer : un rappel de 53 % ne veut rien
    dire sans savoir ce que donne l'absence de méthode.

    Elle est volontairement laissée naïve. La rendre un peu plus maligne
    reviendrait à comparer notre construction de requête à une autre
    construction de requête, c'est-à-dire à déplacer la question.
    """
    lignes = db.execute(
        sql("SELECT id FROM rag_passages WHERE contenu LIKE :q OR titre LIKE :q "
            "ORDER BY id LIMIT :n"),
        {"q": f"%{requete.strip()}%", "n": limite},
    ).fetchall()
    return [l[0] for l in lignes]


def evaluer(db, questions: list[dict], ks: list[int], avec_phase: bool,
            moteur: str = "projet") -> dict:
    """Pour chaque question, le rang du passage attendu — ou None s'il n'y est pas.

    On demande toujours max(ks) résultats, puis on tronque. Lancer une
    recherche par valeur de k interrogerait le moteur plusieurs fois sur la
    même question, ce qui ne changerait rien au classement mais rendrait la
    mesure plus lente et, avec un moteur non déterministe, incohérente.
    """
    profondeur = max(ks)
    rangs: list[int | None] = []
    manques: list[dict] = []

    for q in questions:
        attendu = q.get("passage_attendu")
        if moteur == "reference":
            trouves = reference(db, q["question"], profondeur)
        else:
            trouves = [p.id for p in rag.rechercher(
                db,
                q["question"],
                phase=q.get("phase") if avec_phase else None,
                limite=profondeur,
            )]
        rang = None
        for i, pid in enumerate(trouves, start=1):
            if pid == attendu:
                rang = i
                break
        rangs.append(rang)
        if rang is None or rang > min(ks):
            manques.append({"question": q["question"], "attendu": attendu,
                            "rang": rang, "obtenus": trouves[:3]})

    total = len(rangs)
    mesures = {}
    for k in sorted(ks):
        succes = sum(1 for r in rangs if r is not None and r <= k)
        bas, haut = wilson(succes, total)
        mesures[k] = {"succes": succes, "total": total,
                      "rappel": succes / total if total else 0.0,
                      "ic": (bas, haut)}
    return {"mesures": mesures, "manques": manques}


def main() -> int:
    ap = argparse.ArgumentParser(description="Rappel à k de la recherche documentaire.")
    ap.add_argument("--k", type=int, action="append", default=None,
                    help="profondeur à mesurer (répétable). Par défaut 1, 3 et 5.")
    ap.add_argument("--phase", action="store_true",
                    help="filtrer par la phase attendue, comme le fait l'agent "
                         "quand l'étudiant a désigné son étape.")
    ap.add_argument("--reference", action="store_true",
                    help="mesurer la recherche plein texte naïve, pour avoir "
                         "le point de comparaison plutôt qu'un chiffre nu.")
    ap.add_argument("--manques", action="store_true",
                    help="lister les questions dont le passage attendu n'est "
                         "pas remonté.")
    args = ap.parse_args()
    ks = sorted(set(args.k or [1, 3, 5]))

    jeu = json.loads(JEU.read_text(encoding="utf-8"))
    questions = jeu["questions"]

    db = SessionLocal()
    try:
        etat = rag.etat(db)
        if not etat.get("passages"):
            print("Le corpus est vide. Lancez d'abord : python -m scripts.ingerer_rag",
                  file=sys.stderr)
            return 2

        print()
        print("RECHERCHE DOCUMENTAIRE — RAPPEL À K")
        print(f"  corpus       {etat['passages']} passages, "
              f"{etat['documents_actifs']} documents")
        print(f"  recherche    {etat['recherche']}")
        print(f"  moteur       {'référence plein texte' if args.reference else 'construction de requête du projet'}")
        print(f"  filtre phase {'oui' if args.phase and not args.reference else 'non'}")
        print(f"  jeu          {len(questions)} questions")
        print()

        r = evaluer(db, questions, ks, args.phase,
                    moteur="reference" if args.reference else "projet")
        for k, m in r["mesures"].items():
            bas, haut = m["ic"]
            vedette = "  <-- mesure principale" if k == 3 else ""
            print(f"  rappel à {k} : {pct(m['rappel']):>5}   "
                  f"[{pct(bas)} ; {pct(haut)}]   "
                  f"{m['succes']}/{m['total']}{vedette}")

        print()
        print("  Intervalles de Wilson à 95 %. Deux configurations ne sont")
        print("  tenues pour différentes que si leurs intervalles ne se")
        print("  recouvrent pas — seuil fixé avant la mesure.")

        if args.manques and r["manques"]:
            print()
            print(f"  {len(r['manques'])} questions à revoir :")
            for m in r["manques"]:
                rang = m["rang"] if m["rang"] else "absent"
                print(f"    « {m['question']} »")
                print(f"      attendu {m['attendu']}, rang {rang}, "
                      f"remontés {m['obtenus']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
