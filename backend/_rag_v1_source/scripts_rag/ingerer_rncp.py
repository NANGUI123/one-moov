"""Rafraîchit les fiches RNCP depuis les données ouvertes France Compétences.

    python -m scripts.ingerer_rncp           # rafraîchit les fiches connues
    python -m scripts.ingerer_rncp --colonnes  # affiche les colonnes du fichier

AVERTISSEMENT, à lire avant la première exécution
-------------------------------------------------
Ce script n'a PAS pu être exécuté contre le vrai fichier pendant le
développement : l'environnement de build n'a pas d'accès sortant vers
data.gouv.fr. Les noms de colonnes attendus ci-dessous viennent de la
documentation du jeu de données, pas d'une lecture du fichier.

C'est pourquoi le script refuse d'écrire quoi que ce soit s'il ne
reconnaît pas les colonnes. Il affiche alors celles qu'il a trouvées, et
il suffit de corriger la table CORRESPONDANCES ci-dessous. Écrire des
valeurs devinées dans la table des fiches serait exactement l'erreur que
toute l'architecture cherche à éviter : un code RNCP faux a la même
allure qu'un vrai.

Ce que le script fait, et ne fait pas
-------------------------------------
Il met à jour l'état, l'échéance et le remplacement des fiches DÉJÀ
présentes en base. Il n'en ajoute pas de nouvelles et ne crée aucun
rattachement établissement ↔ fiche : ce lien demande un jugement humain
(une fiche nationale couvre des dizaines d'universités, et la présence
d'un établissement dans la liste des certificateurs se vérifie par SIRET,
pas par nom).
"""

from __future__ import annotations

import argparse
import csv
import io
import pathlib
import sys
import zipfile
from datetime import date

import httpx
from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402

# Nom de colonne attendu -> ce qu'on en fait. À corriger après un premier
# passage avec --colonnes si le fichier réel diffère.
CORRESPONDANCES = {
    "numero_fiche": "code",
    "intitule": "intitule",
    "nomenclature_europe_niveau": "niveau_europeen",
    "etat_fiche": "etat",
    "date_fin_enregistrement": "echeance",
    "nouvelle_certification": "remplace_par",
}

ETATS = {
    "publiee": "active",
    "active": "active",
    "inactive": "expiree",
    "expiree": "expiree",
}


def telecharger() -> bytes:
    print(f"Téléchargement : {settings.rncp_export_url}")
    try:
        with httpx.Client(timeout=180, follow_redirects=True) as client:
            reponse = client.get(settings.rncp_export_url)
    except httpx.RequestError as e:
        raise SystemExit(
            f"\nTéléchargement impossible : {e}\n"
            "Vérifie l'accès réseau sortant, ou récupère le fichier à la main "
            "depuis data.gouv.fr et adapte ce script pour le lire localement.\n"
        ) from e

    if reponse.status_code != 200:
        raise SystemExit(f"\nRéponse inattendue : HTTP {reponse.status_code}\n")
    return reponse.content


def ouvrir_csv(contenu: bytes) -> csv.DictReader:
    """Le jeu de données est une archive : on prend le premier CSV trouvé."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(contenu))
    except zipfile.BadZipFile:
        # Le fichier est peut-être servi directement en CSV.
        return csv.DictReader(io.StringIO(contenu.decode("utf-8-sig")), delimiter=";")

    noms = [n for n in archive.namelist() if n.lower().endswith(".csv")]
    if not noms:
        raise SystemExit(f"\nAucun CSV dans l'archive. Contenu : {archive.namelist()}\n")

    print(f"Fichier lu : {noms[0]}")
    brut = archive.read(noms[0]).decode("utf-8-sig", errors="replace")
    # Le séparateur varie selon les exports : on le déduit de l'en-tête.
    entete = brut.split("\n", 1)[0]
    separateur = ";" if entete.count(";") >= entete.count(",") else ","
    return csv.DictReader(io.StringIO(brut), delimiter=separateur)


def normaliser_code(valeur: str) -> str | None:
    valeur = (valeur or "").strip().upper()
    if not valeur:
        return None
    return valeur if valeur.startswith("RNCP") else f"RNCP{valeur}"


def normaliser_date(valeur: str) -> date | None:
    valeur = (valeur or "").strip()
    if not valeur:
        return None
    for motif in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            from datetime import datetime

            return datetime.strptime(valeur, motif).date()
        except ValueError:
            continue
    return None


def main() -> None:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--colonnes", action="store_true",
        help="affiche les colonnes du fichier et s'arrête, sans rien écrire",
    )
    arguments = analyseur.parse_args()

    lecteur = ouvrir_csv(telecharger())
    colonnes = set(lecteur.fieldnames or [])

    if arguments.colonnes:
        print("\nColonnes du fichier :")
        for c in sorted(colonnes):
            print(f"  {c}")
        return

    manquantes = set(CORRESPONDANCES) - colonnes
    if manquantes:
        print("\nLes colonnes attendues ne sont pas dans le fichier.")
        print("Rien n'a été écrit en base — c'est volontaire.\n")
        print("Manquantes :")
        for c in sorted(manquantes):
            print(f"  {c}")
        print("\nColonnes réellement présentes :")
        for c in sorted(colonnes):
            print(f"  {c}")
        print(
            "\nCorrige la table CORRESPONDANCES en haut de ce script, "
            "puis relance.\n"
        )
        raise SystemExit(1)

    db = SessionLocal()
    connus = {
        r[0] for r in db.execute(text("SELECT code FROM fiche_rncp")).fetchall()
    }
    print(f"{len(connus)} fiche(s) suivie(s) en base.")

    vus, modifies = 0, 0
    for ligne in lecteur:
        code = normaliser_code(ligne.get("numero_fiche", ""))
        if not code or code not in connus:
            continue
        vus += 1

        etat = ETATS.get((ligne.get("etat_fiche") or "").strip().lower(), "inconnue")
        echeance = normaliser_date(ligne.get("date_fin_enregistrement", ""))
        remplacant = normaliser_code(ligne.get("nouvelle_certification", ""))
        # On ne pose un remplaçant que s'il est lui-même suivi : sinon la
        # clé étrangère casserait, et suivre la chaîne n'aurait pas de sens.
        if remplacant not in connus:
            remplacant = None

        resultat = db.execute(
            text(
                "UPDATE fiche_rncp SET etat = CAST(:e AS etat_fiche), echeance = :ec, "
                "  remplace_par = :r, verifie_le = CURRENT_DATE "
                "WHERE code = :c AND (etat::text <> :e OR echeance IS DISTINCT FROM :ec "
                "                     OR remplace_par IS DISTINCT FROM :r)"
            ),
            {"e": etat, "ec": echeance, "r": remplacant, "c": code},
        )
        if resultat.rowcount:
            modifies += 1
            print(f"  {code} : état={etat} échéance={echeance} remplacé_par={remplacant or '—'}")

    # Les fiches suivies mais absentes du fichier méritent un signalement :
    # une fiche retirée du répertoire ne doit pas rester affichée « active ».
    db.execute(
        text(
            "UPDATE fiche_rncp SET verifie_le = CURRENT_DATE "
            "WHERE code = ANY(:codes)"
        ),
        {"codes": list(connus)},
    )
    db.commit()

    absentes = len(connus) - vus
    print(f"\n{vus} fiche(s) retrouvée(s), {modifies} mise(s) à jour.")
    if absentes > 0:
        print(
            f"{absentes} fiche(s) suivie(s) n'apparaissent pas dans l'export. "
            "À vérifier une par une sur francecompetences.fr : une fiche "
            "retirée du répertoire ne doit pas rester affichée."
        )
    db.close()


if __name__ == "__main__":
    main()
