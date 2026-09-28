"""Veille sur les sources officielles.

Ce script ne récupère pas de contenu pour alimenter l'application. Il vérifie
seulement si une page officielle a changé depuis le dernier passage, et
signale les faits à revoir. Un humain va ensuite vérifier et met à jour la
valeur avec remplacer_fait.

Ce choix est délibéré. Extraire automatiquement un montant d'une page
administrative est fragile : la mise en page change sans préavis, et une
erreur d'extraction produirait exactement ce qu'on cherche à éviter, une
valeur fausse présentée comme vérifiée. On automatise la détection du
changement, pas la lecture de la valeur.

    python -m scripts.veille_sources
"""

import hashlib
import pathlib
import re
import sys
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.db import engine  # noqa: E402

ENTETES = {
    "User-Agent": "One Moov (projet étudiant HETIC) - veille documentaire",
    "Accept": "text/html,application/xhtml+xml",
}


def empreinte_page(html: str) -> str:
    """Hachage du texte utile, insensible aux variations de mise en page.

    On retire les scripts, les styles et les balises, puis on normalise les
    espaces. Un changement de bannière ou d'identifiant de session ne
    déclenche donc pas de fausse alerte.
    """
    texte = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    texte = re.sub(r"<style.*?</style>", " ", texte, flags=re.S | re.I)
    texte = re.sub(r"<[^>]+>", " ", texte)
    texte = re.sub(r"\s+", " ", texte).strip().lower()
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def verifier() -> None:
    maintenant = datetime.now(timezone.utc)
    changements: list[tuple[str, list[str]]] = []

    with engine.begin() as conn:
        sources = conn.execute(
            text("SELECT id, url, libelle, cles_liees, empreinte FROM surveillance_source")
        ).fetchall()

        if not sources:
            print("Aucune source à surveiller.")
            return

        print(f"{len(sources)} source(s) à vérifier.\n")

        with httpx.Client(timeout=25.0, headers=ENTETES, follow_redirects=True) as client:
            for source_id, url, libelle, cles, ancienne in sources:
                try:
                    reponse = client.get(url)
                    reponse.raise_for_status()
                except Exception as e:  # noqa: BLE001
                    print(f"  {libelle} : injoignable ({type(e).__name__})")
                    conn.execute(
                        text(
                            "UPDATE surveillance_source SET verifie_le = :t, statut = 'erreur' "
                            "WHERE id = :id"
                        ),
                        {"t": maintenant, "id": source_id},
                    )
                    continue

                nouvelle = empreinte_page(reponse.text)

                if ancienne is None:
                    statut = "inchange"
                    print(f"  {libelle} : première empreinte enregistrée")
                elif nouvelle != ancienne:
                    statut = "change"
                    changements.append((libelle, list(cles or [])))
                    print(f"  {libelle} : A CHANGÉ")
                else:
                    statut = "inchange"
                    print(f"  {libelle} : inchangé")

                conn.execute(
                    text(
                        """
                        UPDATE surveillance_source
                        SET empreinte = :emp, verifie_le = :t, statut = :st,
                            change_le = CASE WHEN :st = 'change' THEN :t ELSE change_le END
                        WHERE id = :id
                        """
                    ),
                    {"emp": nouvelle, "t": maintenant, "st": statut, "id": source_id},
                )

        # Faits qui n'ont pas été vérifiés depuis longtemps.
        anciens = conn.execute(
            text(
                "SELECT cle, libelle, jours_depuis_verification FROM fait_en_vigueur "
                "WHERE a_reverifier ORDER BY jours_depuis_verification DESC"
            )
        ).fetchall()

    if changements:
        print("\nPages modifiées, faits à revérifier :")
        for libelle, cles in changements:
            print(f"  {libelle}")
            for cle in cles:
                print(f"     -> {cle}")

    if anciens:
        print("\nFaits non vérifiés depuis plus de 90 jours :")
        for cle, libelle, jours in anciens:
            print(f"  {cle} ({jours} jours) : {libelle}")

    if not changements and not anciens:
        print("\nRien à signaler. Toutes les sources sont à jour.")
    else:
        print(
            "\nPour mettre un fait à jour après vérification :\n"
            "  SELECT remplacer_fait('<cle>', '<nouvelle valeur>', '<url>', '<source>', '<pays>');"
        )


if __name__ == "__main__":
    verifier()
