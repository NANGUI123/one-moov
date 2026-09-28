"""Chiffre le coût d'exploitation réel, par étudiant et par mois.

    python -m scripts.economie
    python -m scripts.economie --etudiants 500

Le jury vérifie en premier les charges d'exploitation : appels au modèle,
hébergement, dépendances fournisseurs. Une charge omise est une erreur
sanctionnée.

Ce script ne devine pas les volumes. Il compte ce que le code consomme
réellement — nombre d'appels au modèle par parcours, taille des prompts —
et multiplie par des tarifs publics. Chaque hypothèse de volume est
étiquetée comme telle et modifiable en tête de fichier.

Ce qui est mesuré, et ce qui est supposé
-----------------------------------------
MESURÉ, depuis le code :
  - le nombre d'appels au modèle pour chaque action de l'étudiant ;
  - la taille des prompts système, qui partent à chaque appel.

SUPPOSÉ, à ajuster :
  - combien de questions un étudiant pose à son chatbot ;
  - combien de rappels il reçoit ;
  - le taux de conversion vers l'offre prémium.

Les tarifs fournisseurs sont ceux relevés en septembre 2026 et doivent être
reconfirmés avant toute présentation.
"""

from __future__ import annotations

import argparse

# --- Parité fixe, depuis 1999 -------------------------------------------
FCFA_PAR_EURO = 655.957
EURO_PAR_DOLLAR = 0.92          # à reconfirmer, le change flotte

# --- Tarifs fournisseurs (relevés septembre 2026, à reconfirmer) --------
TARIFS = {
    # Llama 3.3 70B servi par Groq, en dollars par million de tokens.
    "llm_entree_usd_m": 0.59,
    "llm_sortie_usd_m": 0.79,
    # mistral-embed, endpoint européen, dollars par million de tokens.
    "embeddings_usd_m": 0.11,
    # WhatsApp Cloud API, message de service « utility », zone Afrique.
    # Fourchette large selon les sources : on retient la borne haute.
    "whatsapp_usd_message": 0.02,
    # Hébergement : Render, service web + PostgreSQL.
    "hebergement_usd_mois": 32.0,
    # Commission d'un agrégateur mobile money, en pourcentage.
    "commission_paiement": 0.035,
    # Une personne à mi-temps pour vérifier les faits, tenir les fiches RNCP
    # à jour, répondre au support et réconcilier les paiements manuels.
    # Sans elle, la promesse de fiabilité du produit ne tient pas : ce n'est
    # pas une charge optionnelle, c'est le cœur du service.
    # Ordre de grandeur pour un profil qualifié au Cameroun, à ajuster.
    "salaire_mi_temps_fcfa_mois": 150000,
}

# --- Consommation MESURÉE, depuis le code -------------------------------
#
# Chaque tour de conversation renvoie le prompt système et l'historique.
# Les tailles viennent des prompts réels, comptés à ~4 caractères par token.
MESURE = {
    "orientation_tours": 7,          # 7 champs à remplir en mode guidé
    "orientation_entree_tokens": 349 + 400,   # prompt système + historique
    "orientation_sortie_tokens": 150,

    "roadmap_appels": 1,
    "roadmap_entree_tokens": 290 + 1800,      # prompt + passages RAG + faits
    "roadmap_sortie_tokens": 1200,            # 6 phases rédigées

    "chatbot_entree_tokens": 262 + 1400,      # prompt + passages + historique
    "chatbot_sortie_tokens": 350,

    # Deux appels par question : le jury pose, le correcteur note.
    "entretien_appels_par_question": 2,
    "entretien_entree_tokens": 98 + 600,
    "entretien_sortie_tokens": 300,

    "embedding_question_tokens": 25,
}

# --- HYPOTHÈSES de volume, à ajuster ------------------------------------
HYPOTHESES = {
    "questions_chatbot": 15,         # questions posées au chatbot prémium
    "questions_entretien": 10,       # questions d'entraînement à l'entretien
    "rappels_whatsapp": 6,           # un par étape de la feuille de route
    "taux_prise_chatbot": 0.12,      # part des étudiants qui prennent le prémium
    "taux_prise_prive": 0.04,        # part qui débloque les établissements privés
}

# --- Tarifs de vente, en FCFA -------------------------------------------
PRIX = {
    "roadmap": 100,
    "chatbot": 30000,
    "debloquer_prive": 50000,
}


def fr(montant: float) -> str:
    """Formate un montant à la française, sans abîmer les libellés."""
    return f"{montant:,.0f}".replace(",", "\u202f")


def usd_en_fcfa(montant: float) -> float:
    return montant * EURO_PAR_DOLLAR * FCFA_PAR_EURO


def cout_llm(entree: int, sortie: int, appels: int = 1) -> float:
    """Coût d'un appel au modèle, en dollars."""
    return appels * (
        entree / 1_000_000 * TARIFS["llm_entree_usd_m"]
        + sortie / 1_000_000 * TARIFS["llm_sortie_usd_m"]
    )


def main() -> None:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--etudiants", type=int, default=200,
                           help="nombre d'étudiants actifs par mois")
    arguments = analyseur.parse_args()
    n = arguments.etudiants

    m, h = MESURE, HYPOTHESES

    # --- Coût variable, par étudiant ------------------------------------
    orientation = cout_llm(
        m["orientation_entree_tokens"], m["orientation_sortie_tokens"],
        m["orientation_tours"],
    )
    roadmap = cout_llm(
        m["roadmap_entree_tokens"], m["roadmap_sortie_tokens"], m["roadmap_appels"]
    )
    chatbot = cout_llm(
        m["chatbot_entree_tokens"], m["chatbot_sortie_tokens"], h["questions_chatbot"]
    )
    entretien = cout_llm(
        m["entretien_entree_tokens"], m["entretien_sortie_tokens"],
        h["questions_entretien"] * m["entretien_appels_par_question"],
    )
    # Une requête embeddée par question posée, orientation comprise.
    requetes = m["orientation_tours"] + h["questions_chatbot"]
    embeddings = (
        requetes * m["embedding_question_tokens"] / 1_000_000
        * TARIFS["embeddings_usd_m"]
    )
    whatsapp = h["rappels_whatsapp"] * TARIFS["whatsapp_usd_message"]

    print(f"\n{'='*66}")
    print("COÛT VARIABLE PAR ÉTUDIANT")
    print(f"{'='*66}\n")

    lignes = [
        ("Orientation (7 tours)", orientation, "mesuré"),
        ("Feuille de route (1 appel)", roadmap, "mesuré"),
        ("Chatbot (%d questions)" % h["questions_chatbot"], chatbot, "hypothèse"),
        ("Entretien (%d questions × 2 appels)" % h["questions_entretien"],
         entretien, "hypothèse"),
        ("Embeddings (%d requêtes)" % requetes, embeddings, "mesuré"),
        ("Rappels WhatsApp (%d)" % h["rappels_whatsapp"], whatsapp, "hypothèse"),
    ]

    print(f"{'Poste':<40s} {'USD':>9s} {'FCFA':>9s}   source")
    print("-" * 78)
    for libelle, usd, source in lignes:
        print(f"{libelle:<40s} {usd:>9.4f} {usd_en_fcfa(usd):>9.1f}   {source}")

    # Un étudiant gratuit ne va pas au-delà de l'orientation et de la roadmap.
    gratuit = orientation + roadmap + embeddings * 0.4
    premium = sum(u for _, u, _ in lignes)

    print("-" * 78)
    print(f"{'Parcours gratuit (orientation + roadmap)':<40s} "
          f"{gratuit:>9.4f} {usd_en_fcfa(gratuit):>9.1f}")
    print(f"{'Parcours prémium complet':<40s} "
          f"{premium:>9.4f} {usd_en_fcfa(premium):>9.1f}")

    # --- Marge par offre -------------------------------------------------
    print(f"\n{'='*66}")
    print("MARGE PAR OFFRE")
    print(f"{'='*66}\n")
    print(f"{'Offre':<26s} {'Prix':>8s} {'Coût':>8s} {'Commission':>11s} {'Marge':>9s} {'%':>6s}")
    print("-" * 74)

    offres = [
        ("Feuille de route", PRIX["roadmap"], usd_en_fcfa(gratuit)),
        ("Chatbot prémium", PRIX["chatbot"], usd_en_fcfa(chatbot + entretien + whatsapp)),
        ("Déblocage privé", PRIX["debloquer_prive"], usd_en_fcfa(roadmap)),
    ]
    for libelle, prix, cout in offres:
        commission = prix * TARIFS["commission_paiement"]
        marge = prix - cout - commission
        part = marge / prix if prix else 0
        print(f"{libelle:<26s} {prix:>8.0f} {cout:>8.1f} {commission:>11.1f} "
              f"{marge:>9.1f} {part:>5.0%}")

    # --- Compte de résultat mensuel --------------------------------------
    print(f"\n{'='*66}")
    print(f"MENSUEL — {n} étudiants actifs")
    print(f"{'='*66}\n")

    n_chatbot = n * h["taux_prise_chatbot"]
    n_prive = n * h["taux_prise_prive"]

    revenus = (
        n * PRIX["roadmap"]
        + n_chatbot * PRIX["chatbot"]
        + n_prive * PRIX["debloquer_prive"]
    )
    commissions = revenus * TARIFS["commission_paiement"]
    variable = (
        n * usd_en_fcfa(gratuit)
        + n_chatbot * usd_en_fcfa(chatbot + entretien + whatsapp)
    )
    hebergement = usd_en_fcfa(TARIFS["hebergement_usd_mois"])
    salaire = TARIFS["salaire_mi_temps_fcfa_mois"]
    fixe = hebergement + salaire

    print(f"{'Revenus':<44s} {fr(revenus):>12s} FCFA")
    print(f"{'  dont feuilles de route (%d)' % n:<44s} "
          f"{fr(n * PRIX['roadmap']):>12s}")
    print(f"{'  dont chatbot (%.0f, soit %.0f%%)' % (n_chatbot, h['taux_prise_chatbot']*100):<44s} "
          f"{fr(n_chatbot * PRIX['chatbot']):>12s}")
    print(f"{'  dont déblocage privé (%.0f)' % n_prive:<44s} "
          f"{fr(n_prive * PRIX['debloquer_prive']):>12s}")
    print()
    print(f"{'Charges variables (IA, WhatsApp)':<44s} {fr(-variable):>12s}")
    print(f"{'Commissions de paiement (3,5 %)':<44s} {fr(-commissions):>12s}")
    print(f"{'Hébergement':<44s} {fr(-hebergement):>12s}")
    print(f"{'Vérification des faits et support':<44s} {fr(-salaire):>12s}")
    print("-" * 60)
    resultat = revenus - variable - commissions - fixe
    print(f"{'Résultat':<44s} {fr(resultat):>12s} FCFA")
    print(f"{'':<44s} {fr(resultat / FCFA_PAR_EURO):>12s} €")

    # --- Seuil de rentabilité --------------------------------------------
    marge_unitaire = (
        PRIX["roadmap"] * (1 - TARIFS["commission_paiement"]) - usd_en_fcfa(gratuit)
        + h["taux_prise_chatbot"] * (
            PRIX["chatbot"] * (1 - TARIFS["commission_paiement"])
            - usd_en_fcfa(chatbot + entretien + whatsapp)
        )
        + h["taux_prise_prive"] * PRIX["debloquer_prive"] * (1 - TARIFS["commission_paiement"])
    )

    print(f"\n{'='*66}")
    print("SEUIL DE RENTABILITÉ")
    print(f"{'='*66}\n")
    print(f"Marge par étudiant actif : {fr(marge_unitaire)} FCFA")
    if marge_unitaire > 0:
        seuil = fixe / marge_unitaire
        print(f"Seuil de rentabilité     : {seuil:.0f} étudiants actifs par mois")
        print(f"                           soit environ {seuil/30:.1f} par jour")
    else:
        print("Marge unitaire négative : le modèle ne couvre pas ses coûts.")

    # --- Ce qui n'est pas dans ce calcul ---------------------------------
    print(f"\n{'='*66}")
    print("CE QUI N'EST PAS DANS CE CALCUL")
    print(f"{'='*66}\n")
    for ligne in (
        "Le temps de l'équipe. Cinq personnes, non rémunérées à ce stade.",
        "L'acquisition client. Aucun budget marketing n'est chiffré ici,",
        "  et le coût d'acquisition reste à établir sur le terrain.",
        "La montée en charge du support : un mi-temps suffit à 200 étudiants,",
        "  pas à 2 000. La charge croît par paliers, pas linéairement.",
        "La réconciliation manuelle des paiements tant que l'agrégateur",
        "  n'est pas en production.",
        "Les frais juridiques et la conformité (loi camerounaise 2024/017).",
        "L'hébergement retenu est un plan à 32 $/mois. Le plan gratuit",
        "  expire à 30 jours pour la base de données.",
    ):
        print(f"  - {ligne}" if not ligne.startswith(" ") else f"  {ligne}")

    print(
        "\nLes tarifs fournisseurs datent de septembre 2026 et doivent être\n"
        "reconfirmés. La fourchette WhatsApp est large selon les sources :\n"
        "la borne haute est retenue ici.\n"
    )


if __name__ == "__main__":
    main()
