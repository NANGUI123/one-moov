"""Parcours de paiement, par HTTP.

    python -m scripts.tester_paiements

Suppose l'API lancée en local. Vérifie surtout les trois choses qui font
qu'un système de paiement est sûr ou non :

  - le montant vient du serveur, jamais du navigateur ;
  - un webhook ne peut pas faire passer un paiement à « réussi » par son
    seul contenu ;
  - rejouer un webhook ne duplique rien.

Le script tape vite : lancer l'API avec des quotas desserrés.
"""

from __future__ import annotations

import pathlib
import sys

import httpx
from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402

BASE = "http://127.0.0.1:8000/api"
FANTOME = "00000000-0000-0000-0000-000000000000"

reussis = echecs = 0


def verifier(intitule: str, condition: bool, detail: str = "") -> None:
    global reussis, echecs
    if condition:
        reussis += 1
        print(f"  ok    {intitule}")
    else:
        echecs += 1
        print(f"  ÉCHEC {intitule}{chr(10) + '        ' + detail if detail else ''}")


client = httpx.Client(timeout=30)
db = SessionLocal()


def compter(requete: str, **params) -> int:
    return db.execute(text(requete), params).scalar() or 0


print("\nOptions de paiement")
options = client.get(f"{BASE}/paiements/options").json()
verifier(
    "le Congo expose MTN et Airtel, pas Orange",
    options["pays_ouverts"]["Congo-Brazzaville"] == ["airtel", "mtn"],
    str(options["pays_ouverts"]),
)
verifier("le plancher opérateur est annoncé", options["montant_minimum_fcfa"] == 100)
verifier(
    "aucun tarif n'est sous le plancher",
    all(m >= 100 for m in options["tarifs_fcfa"].values()),
    str(options["tarifs_fcfa"]),
)

print("\nCréation")
reponse = client.post(
    f"{BASE}/paiements",
    json={"objet": "roadmap_public", "pays": "Cameroun",
          "operateur": "mtn", "telephone": "699887766"},
)
verifier("un paiement est créé", reponse.status_code == 201, reponse.text[:150])
paiement_id = reponse.json().get("paiement_id", "")
verifier(
    "le montant vient du serveur, pas du client",
    reponse.json().get("montant_fcfa") == 100,
)

refus = client.post(
    f"{BASE}/paiements",
    json={"objet": "roadmap_public", "pays": "Congo-Brazzaville",
          "operateur": "orange", "telephone": "061234567"},
)
verifier("Orange au Congo est refusé", refus.status_code == 422, refus.text[:120])
verifier(
    "le refus dit quels opérateurs existent vraiment",
    "irtel" in refus.text,
    refus.text[:160],
)

verifier(
    "un objet de paiement inconnu est refusé",
    client.post(
        f"{BASE}/paiements",
        json={"objet": "inconnu", "pays": "Cameroun",
              "operateur": "mtn", "telephone": "699887766"},
    ).status_code == 422,
)

print("\nWebhook : le corps ne fait jamais foi")
avant = compter("SELECT count(*) FROM paiement")

envoi = client.post(
    f"{BASE}/paiements/webhook/pawapay",
    json={"depositId": FANTOME, "status": "COMPLETED"},
)
verifier("un webhook pour un paiement inconnu répond 200", envoi.status_code == 200)
verifier(
    "et ne crée aucun paiement fantôme",
    compter("SELECT count(*) FROM paiement WHERE id = :i", i=FANTOME) == 0,
)
verifier(
    "le nombre de paiements est inchangé",
    compter("SELECT count(*) FROM paiement") == avant,
)

print("\nIdempotence")
# On rouvre le paiement, puis on rejoue le webhook plusieurs fois.
db.execute(
    text("UPDATE paiement SET statut = 'en_attente', clos_le = NULL WHERE id = :i"),
    {"i": paiement_id},
)
db.commit()

for _ in range(3):
    client.post(
        f"{BASE}/paiements/webhook/pawapay",
        json={"depositId": paiement_id, "status": "COMPLETED"},
    )

verifier(
    "rejouer le webhook ne duplique pas le paiement",
    compter("SELECT count(*) FROM paiement WHERE id = :i", i=paiement_id) == 1,
)
verifier(
    "le nombre total de paiements n'a pas bougé",
    compter("SELECT count(*) FROM paiement") == avant,
)

print("\nConsultation")
lecture = client.get(f"{BASE}/paiements/{paiement_id}")
verifier("le paiement se consulte", lecture.status_code == 200, lecture.text[:120])
verifier(
    "le statut renvoyé fait partie des statuts connus",
    lecture.json()["statut"]
    in ("en_attente", "en_cours", "reussi", "echoue", "abandonne"),
    lecture.text[:120],
)
verifier(
    "un paiement inexistant renvoie 404",
    client.get(f"{BASE}/paiements/11111111-1111-1111-1111-111111111111").status_code == 404,
)

# Nettoyage : le paiement de test n'a pas à rester.
db.execute(text("DELETE FROM paiement WHERE id = :i"), {"i": paiement_id})
db.commit()
db.close()

print(f"\n{reussis} réussis, {echecs} échec(s)\n")
sys.exit(1 if echecs else 0)
