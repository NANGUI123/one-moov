"""Réconciliation des paiements.

    python -m scripts.reconcilier

Le cas qu'on rattrape ici n'est pas rare, il est courant : l'étudiant a
payé, mais le webhook n'est jamais arrivé. Réseau instable, serveur en
redéploiement, timeout côté fournisseur. Sans ce script, l'étudiant est
débité et n'obtient rien — le pire échec possible pour ce produit.

À faire tourner toutes les deux ou trois minutes, en tâche planifiée.

Le script ne fait jamais confiance à ce qu'il a en base : pour chaque
paiement encore ouvert, il interroge l'API de statut du fournisseur et
écrit ce qu'elle répond. Un paiement resté sans réponse au-delà du délai
d'expiration est clos en « abandonné » — sauf en mode manuel, où seule une
validation humaine peut le faire avancer.
"""

from __future__ import annotations

import pathlib
import sys

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402
from app.services import paiement as svc  # noqa: E402

# Au-delà, un paiement jamais confirmé est considéré comme abandonné. Les
# opérateurs mobile money expirent en général leurs demandes bien avant.
DELAI_ABANDON_MINUTES = 30

# Un paiement qu'on a déjà interrogé un grand nombre de fois sans réponse
# nette n'apportera rien de plus : on arrête d'appeler l'API pour lui.
VERIFICATIONS_MAX = 40


def main() -> None:
    fournisseur = svc.fournisseur_actif()
    if fournisseur == "manuel":
        print(
            "Fournisseur « manuel » : aucune API à interroger. "
            "Les paiements attendent une validation humaine."
        )
        return

    db = SessionLocal()

    ouverts = db.execute(
        text(
            "SELECT id::text, statut::text, verifications, "
            "       EXTRACT(EPOCH FROM (now() - cree_le)) / 60 AS age_minutes "
            "FROM paiement "
            "WHERE statut IN ('en_attente','en_cours') "
            "  AND fournisseur = :f "
            "  AND (prochaine_verification IS NULL OR prochaine_verification <= now()) "
            "ORDER BY cree_le "
            "LIMIT 200"
        ),
        {"f": fournisseur},
    ).fetchall()

    if not ouverts:
        print("Aucun paiement à réconcilier.")
        db.close()
        return

    print(f"{len(ouverts)} paiement(s) ouvert(s) à vérifier.\n")
    confirmes = echoues = abandonnes = inchanges = 0

    for identifiant, statut_connu, verifications, age in ouverts:
        # Trop vieux, ou trop interrogé : on clôt.
        if age > DELAI_ABANDON_MINUTES or verifications >= VERIFICATIONS_MAX:
            db.execute(
                text(
                    "UPDATE paiement SET statut = 'abandonne', clos_le = now(), "
                    "  prochaine_verification = NULL, "
                    "  motif_echec = COALESCE(motif_echec, 'jamais confirmé par le fournisseur') "
                    "WHERE id = :i"
                ),
                {"i": identifiant},
            )
            abandonnes += 1
            print(f"  {identifiant[:8]} : abandonné après {int(age)} min")
            continue

        try:
            etat = svc.etat(identifiant)
        except svc.ErreurPaiement as e:
            # Le fournisseur est injoignable : on réessaiera au prochain
            # passage plutôt que de clore à tort.
            db.execute(
                text(
                    "UPDATE paiement SET verifications = verifications + 1, "
                    "  prochaine_verification = now() + interval '2 minutes' "
                    "WHERE id = :i"
                ),
                {"i": identifiant},
            )
            print(f"  {identifiant[:8]} : vérification impossible ({e})")
            continue

        if etat.statut == statut_connu:
            db.execute(
                text(
                    "UPDATE paiement SET verifications = verifications + 1, "
                    "  prochaine_verification = now() + interval '1 minute' "
                    "WHERE id = :i"
                ),
                {"i": identifiant},
            )
            inchanges += 1
            continue

        clos = etat.statut in ("reussi", "echoue")
        db.execute(
            text(
                "UPDATE paiement SET statut = CAST(:s AS statut_paiement), "
                "  reference_fournisseur = COALESCE(:r, reference_fournisseur), "
                "  motif_echec = COALESCE(:m, motif_echec), "
                "  verifications = verifications + 1, "
                "  clos_le = CASE WHEN :c THEN now() ELSE clos_le END, "
                "  prochaine_verification = CASE WHEN :c THEN NULL "
                "       ELSE now() + interval '1 minute' END "
                "WHERE id = :i"
            ),
            {"s": etat.statut, "r": etat.reference, "m": etat.motif,
             "c": clos, "i": identifiant},
        )

        if etat.statut == "reussi":
            confirmes += 1
            print(f"  {identifiant[:8]} : CONFIRMÉ — webhook jamais reçu, rattrapé ici")
        elif etat.statut == "echoue":
            echoues += 1
            print(f"  {identifiant[:8]} : échoué ({etat.motif or 'sans motif'})")

    db.commit()

    # Minimisation : les numéros de téléphone des paiements clos depuis
    # longtemps n'ont plus de raison d'être conservés.
    purges = db.execute(text("SELECT purger_numeros_paiement(30)")).scalar()
    db.commit()

    print(
        f"\n{confirmes} confirmé(s), {echoues} échoué(s), "
        f"{abandonnes} abandonné(s), {inchanges} inchangé(s)."
    )
    if purges:
        print(f"{purges} numéro(s) de téléphone purgé(s).")
    db.close()


if __name__ == "__main__":
    main()
