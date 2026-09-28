"""Agent 1, étape 2 : le matching.

Les établissements et les villes viennent de la base, jamais du modèle.
C'est le point qui distingue One Moov d'un simple assistant conversationnel :
un établissement proposé existe, ses frais sont ceux de la base, et la date
de dernière vérification accompagne la proposition.

La logique de classement vit dans la fonction SQL matcher_etablissements.
Ce module prépare les paramètres et traduit le résultat. Une seule source
de vérité pour le classement, pas deux implémentations à maintenir.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.schemas import (
    Profil, Secteur, EtablissementPropose, VilleProposee, Niveau, Formation,
)
from app.services import embeddings

_SQL_MATCH = text(
    """
    SELECT etablissement_id, nom, ville, secteur, frais, description,
           site_web, verifie_le, score
    FROM matcher_etablissements(
        CAST(:niveau AS niveau_diplome),
        CAST(:formation AS type_formation),
        CAST(:langue AS langue_ens),
        :budget,
        CAST(:secteurs AS secteur_etablissement[]),
        CAST(:emb AS vector),
        :narratif,
        :limite
    )
    """
)

_SQL_VILLES = text(
    """
    SELECT nom, region, cout_vie_mensuel, loyer_moyen_studio, description
    FROM ville
    WHERE nom = ANY(:noms)
    ORDER BY cout_vie_mensuel ASC
    """
)

_SQL_VILLES_BUDGET = text(
    """
    SELECT nom, region, cout_vie_mensuel, loyer_moyen_studio, description
    FROM ville
    WHERE (cout_vie_mensuel + loyer_moyen_studio) <= :budget_max
    ORDER BY (cout_vie_mensuel + loyer_moyen_studio) ASC
    LIMIT :limite
    """
)


def _budget_scolarite(profil: Profil) -> int:
    """Budget annuel de scolarité.

    S'il n'est pas renseigné, on l'estime généreusement pour ne pas écarter
    des établissements que l'étudiant pourrait financer autrement, par une
    bourse ou un soutien familial. Le filtre reste un garde-fou, pas un juge.
    """
    if profil.budget_scolarite_an is not None:
        return profil.budget_scolarite_an
    if profil.budget_mensuel:
        return max(12000, profil.budget_mensuel * 12)
    return 20000


def chercher_etablissements(
    db: Session,
    profil: Profil,
    secteurs: list[Secteur],
    limite: int = 8,
) -> list[EtablissementPropose]:
    """Établissements éligibles, classés par pertinence."""
    narratif = " ".join(
        filter(None, [profil.domaine, profil.projet_etudes, profil.projet_pro])
    ).strip()

    vecteur = embeddings.en_pgvector(embeddings.encoder(narratif)) if narratif else None

    lignes = db.execute(
        _SQL_MATCH,
        {
            "niveau": (profil.niveau or Niveau.master).value,
            "formation": (profil.formation or Formation.initiale).value,
            "langue": profil.langue_enseignement.value,
            "budget": _budget_scolarite(profil),
            "secteurs": [s.value for s in (secteurs or [Secteur.public])],
            "emb": vecteur,
            "narratif": narratif,
            "limite": limite,
        },
    ).fetchall()

    return [
        EtablissementPropose(
            id=l[0], nom=l[1], ville=l[2], secteur=l[3],
            frais_scolarite_an=int(l[4]), description=l[5],
            site_web=l[6], verifie_le=l[7].isoformat(),
        )
        for l in lignes
    ]


def villes_des_etablissements(
    db: Session, etablissements: list[EtablissementPropose]
) -> list[VilleProposee]:
    """Villes correspondant aux établissements retenus."""
    noms = list(dict.fromkeys(e.ville for e in etablissements))
    if not noms:
        return []

    lignes = db.execute(_SQL_VILLES, {"noms": noms}).fetchall()
    return [
        VilleProposee(
            nom=l[0], region=l[1], cout_vie_mensuel=int(l[2]),
            loyer_moyen_studio=int(l[3]), pourquoi=l[4],
        )
        for l in lignes
    ]


def villes_dans_budget(db: Session, budget_mensuel: Optional[int], limite: int = 3) -> list[VilleProposee]:
    """Villes compatibles avec le budget, quand aucun établissement ne ressort."""
    plafond = budget_mensuel or 900
    lignes = db.execute(
        _SQL_VILLES_BUDGET, {"budget_max": plafond, "limite": limite}
    ).fetchall()
    return [
        VilleProposee(
            nom=l[0], region=l[1], cout_vie_mensuel=int(l[2]),
            loyer_moyen_studio=int(l[3]), pourquoi=l[4],
        )
        for l in lignes
    ]


def analyser_budget(profil: Profil, villes: list[VilleProposee]) -> str:
    """Compare le budget annoncé au coût réel des villes proposées.

    Cette analyse s'appuie uniquement sur des chiffres de la base. Le modèle
    n'intervient pas, donc aucun montant ne peut être inventé.
    """
    if not villes:
        return "Aucune ville n'a pu être comparée à ton budget pour le moment."

    budget = profil.budget_mensuel
    couts = [(v.nom, v.cout_vie_mensuel + v.loyer_moyen_studio) for v in villes]
    moins_chere = min(couts, key=lambda c: c[1])

    if budget is None:
        return (
            f"Les villes proposées demandent entre {min(c for _, c in couts)} "
            f"et {max(c for _, c in couts)} euros par mois, loyer compris."
        )

    accessibles = [nom for nom, cout in couts if cout <= budget]

    if len(accessibles) == len(couts):
        return (
            f"Avec {budget} euros par mois, toutes les villes proposées sont "
            f"dans tes moyens, loyer compris."
        )
    if accessibles:
        return (
            f"Avec {budget} euros par mois, {', '.join(accessibles)} "
            f"reste{'nt' if len(accessibles) > 1 else ''} accessible"
            f"{'s' if len(accessibles) > 1 else ''}. Les autres demandent un budget supérieur."
        )
    return (
        f"Avec {budget} euros par mois, les villes proposées sont au-dessus de tes moyens. "
        f"La plus abordable, {moins_chere[0]}, demande environ {moins_chere[1]} euros "
        f"par mois loyer compris. Une bourse ou un logement en résidence changerait ce calcul."
    )
