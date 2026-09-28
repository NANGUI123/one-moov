"""Réconciliation des actions hors ligne, par HTTP.

    python -m scripts.tester_synchronisation

Ce que ce script cherche à prendre en défaut
--------------------------------------------
Une file d'attente qui remonte des actions vieilles de plusieurs heures est
l'endroit où les bugs sont les plus difficiles à voir : rien ne plante, une
donnée disparaît simplement. Les scénarios ci-dessous rejouent les situations
qui font perdre du travail dans la vraie vie.

    Deux appareils, deux étapes différentes   les deux doivent survivre.
    Deux appareils, la même étape             la plus récente gagne, et elle
                                              gagne même si elle arrive en
                                              second ET en premier.
    Un lot rejoué                             le résultat ne bouge pas.
    Une horloge en avance                     ne gagne pas pour toujours.
    Une sauvegarde de compte                  ne doit pas écraser en bloc
                                              l'arbitrage étape par étape.

Suppose l'API lancée en local, SMTP non configuré.
"""
import os
import re
import subprocess
import uuid
from datetime import datetime, timedelta, timezone

import httpx

B = "http://127.0.0.1:8000/api"
EMAIL = "synchro.test@example.com"
MDP = "une phrase de passe correcte"
ok = fail = 0


def v(nom, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ok    {nom}")
    else:
        fail += 1
        print(f"  ECHEC {nom} {detail}")


class ClientTeste(httpx.Client):
    def request(self, *args, **kwargs):
        reponse = super().request(*args, **kwargs)
        if reponse.status_code == 429:
            print(
                "\nLe quota anti-rafale a coupé le test. Relance l'API avec :\n"
                "  QUOTA_RAFALE=500 QUOTA_HORAIRE=5000 QUOTA_MODELE_HORAIRE=3000 "
                "./lancer_dev.sh\n"
            )
            raise SystemExit(2)
        return reponse


c = ClientTeste(timeout=30)

MAINTENANT = datetime.now(timezone.utc)


def action(type_, charge, decalage_minutes=0):
    """Fabrique une action datée relativement à maintenant."""
    return {
        "id": str(uuid.uuid4()),
        "type": type_,
        "charge": charge,
        "horodatage": (MAINTENANT + timedelta(minutes=decalage_minutes)).isoformat(),
    }


def sync(actions, jeton):
    return c.post(
        f"{B}/synchronisation",
        json={"actions": actions},
        headers={"Authorization": f"Bearer {jeton}"},
    )


# --------------------------------------------------------------- ouverture

subprocess.run(
    ["su", "postgres", "-c",
     f"psql -d onemoov -c \"DELETE FROM utilisateur WHERE email='{EMAIL}'\""],
    capture_output=True,
)

c.post(f"{B}/comptes/inscription", json={"email": EMAIL, "mot_de_passe": MDP, "pays": "Congo-Brazzaville"})
journal = open(os.environ.get("JOURNAL", "/tmp/onemoov-api.log")).read()
codes = re.findall(rf"code de vérification de {re.escape(EMAIL)} est (\d{{6}})", journal)
r = c.post(f"{B}/comptes/verification", json={"email": EMAIL, "code": codes[-1]})
JETON = r.json()["jeton"]
AUTH = {"Authorization": f"Bearer {JETON}"}

print("\nContrôle d'accès")
r = c.post(f"{B}/synchronisation", json={"actions": []})
v("sans jeton, la synchronisation refuse", r.status_code == 401)

print("\nAvant toute feuille de route")
r = sync([action("etape", {"index": 0, "fait": True})], JETON)
v("une étape cochée sans feuille de route est différée",
  r.status_code == 200 and len(r.json()["differees"]) == 1, r.text[:150])
v("elle n'est pas comptée comme traitée", r.json()["traitees"] == [])

# On pose une feuille de route, comme le ferait la sauvegarde automatique.
ROADMAP = {"resume": "Test", "etapes": [{"ordre": i, "titre": f"Étape {i}"} for i in range(8)]}
r = c.put(
    f"{B}/comptes/sauvegarde",
    json={"profil": {"domaine": "informatique"}, "roadmap": ROADMAP},
    headers=AUTH,
)
v("la feuille de route est enregistrée", r.status_code == 200, r.text[:120])

print("\nDeux appareils, deux étapes différentes")
r = sync(
    [
        action("etape", {"index": 2, "fait": True}, -60),   # le téléphone, il y a une heure
        action("etape", {"index": 5, "fait": True}, -10),   # le cybercafé, il y a dix minutes
    ],
    JETON,
)
etat = r.json()["etat"]
v("les deux étapes survivent", etat["etapes_faites"] == [2, 5], etat)

print("\nDeux appareils, la même étape")
# L'action la plus ancienne arrive EN DERNIER : c'est exactement le cas d'un
# téléphone qui retrouve du réseau après coup.
r = sync([action("etape", {"index": 5, "fait": False}, -30)], JETON)
v("une action plus ancienne ne défait pas une plus récente",
  r.json()["etat"]["etapes_faites"] == [2, 5], r.json()["etat"])
v("elle est tout de même retirée de la file",
  len(r.json()["traitees"]) == 1 and r.json()["differees"] == [])
v("le verdict dit pourquoi", r.json()["detail"][0]["resultat"] == "anterieure")

r = sync([action("etape", {"index": 5, "fait": False}, -5)], JETON)
v("une action plus récente, elle, décoche bien",
  r.json()["etat"]["etapes_faites"] == [2], r.json()["etat"])

print("\nUn lot rejoué")
rejoue = action("etape", {"index": 3, "fait": True}, -2)
premier = sync([rejoue], JETON).json()["etat"]["etapes_faites"]
second = sync([rejoue], JETON).json()["etat"]["etapes_faites"]
v("rejouer le même lot ne change rien", premier == second == [2, 3], (premier, second))

print("\nHorloge de l'appareil")
# Un téléphone réglé sur 2030 gagnerait tous les arbitrages à venir.
r = sync([action("etape", {"index": 6, "fait": True}, 60 * 24 * 365 * 4)], JETON)
v("une date très en avance est acceptée", 6 in r.json()["etat"]["etapes_faites"])
r = sync([action("etape", {"index": 6, "fait": False}, 1)], JETON)
v("mais elle est ramenée à l'heure du serveur, donc rattrapable",
  6 not in r.json()["etat"]["etapes_faites"], r.json()["etat"])
v("le serveur publie son heure", "horloge" in r.json())

print("\nLe profil se fusionne sans rien perdre")
r = sync(
    [action("profil", {"profil": {"domaine": "droit", "niveau": "master"}}, 30)],
    JETON,
)
profil = r.json()["etat"]["profil"]
v("un profil plus récent gagne sur les champs communs", profil["domaine"] == "droit", profil)
v("il conserve ce qu'il apporte", profil.get("niveau") == "master", profil)

r = sync(
    [action("profil", {"profil": {"domaine": "commerce", "budget_mensuel": 700}}, -120)],
    JETON,
)
profil = r.json()["etat"]["profil"]
v("un profil plus ancien ne recouvre pas les champs communs",
  profil["domaine"] == "droit", profil)
v("mais ses champs inconnus sont conservés", profil.get("budget_mensuel") == 700, profil)

print("\nLa sauvegarde du compte ne défait pas l'arbitrage")
avant = c.get(f"{B}/comptes/moi", headers=AUTH).json()["etapes_faites"]
c.put(f"{B}/comptes/sauvegarde", json={"roadmap": ROADMAP}, headers=AUTH)
apres = c.get(f"{B}/comptes/moi", headers=AUTH).json()["etapes_faites"]
v("une sauvegarde sans étapes laisse la progression intacte", avant == apres, (avant, apres))

c.put(f"{B}/comptes/sauvegarde", json={"roadmap": ROADMAP, "etapes_faites": [1]}, headers=AUTH)
apres = c.get(f"{B}/comptes/moi", headers=AUTH).json()["etapes_faites"]
v("une sauvegarde qui les fournit les applique", apres == [1], apres)

print("\nAucun message ne peut passer par ce chemin")
r = c.post(
    f"{B}/synchronisation",
    json={"actions": [{"id": "x", "type": "message",
                       "horodatage": MAINTENANT.isoformat(),
                       "charge": {"texte": "ma question"}}]},
    headers=AUTH,
)
v("le type « message » est rejeté par le contrat", r.status_code == 422, r.text[:150])

r = sync([action("etape", {"index": 0, "fait": True, "texte": "ma question"}, 5)], JETON)
v("un champ en trop dans la charge est ignoré, pas enregistré",
  r.status_code == 200 and 0 in r.json()["etat"]["etapes_faites"])
trace = subprocess.run(
    ["su", "postgres", "-c",
     "psql -d onemoov -tAc \"SELECT count(*) FROM roadmap_enregistree "
     "WHERE etapes_horodatage::text ILIKE '%question%'\""],
    capture_output=True, text=True,
).stdout.strip()
v("rien de ce texte n'a atterri en base", trace == "0", trace)

print("\nCharges mal formées")
r = sync([action("etape", {"index": -1, "fait": True})], JETON)
v("un indice négatif est refusé proprement",
  r.json()["detail"][0]["resultat"] == "charge_invalide", r.json()["detail"])
r = sync([action("etape", {"index": 1, "fait": "oui"})], JETON)
v("un booléen attendu et reçu en texte est refusé",
  r.json()["detail"][0]["resultat"] == "charge_invalide", r.json()["detail"])

print("\nLe parcours guidé hors ligne")
r = c.get(f"{B}/orientation/etapes-guidees")
etapes = r.json()["etapes"]
v("les questions du parcours guidé sont publiées", len(etapes) >= 5, r.text[:120])
v("chacune porte son champ et sa question",
  all("champ" in e and "question" in e for e in etapes))

r = c.post(
    f"{B}/orientation/profil-guide",
    json={"reponses": {
        "domaine": "Informatique et IA", "niveau": "Maîtrise",
        "formation": "Alternance", "budget_mensuel": "600 à 800 €",
        "pays_origine": "Cameroun", "projet_etudes": "Devenir data engineer",
        "projet_pro": "Travailler en Afrique centrale",
    }},
)
p = r.json()
v("les sept réponses valident le profil d'un coup", p["complet"] is True, r.text[:200])
v("« Maîtrise » est converti en master", p["profil"]["niveau"] == "master", p["profil"])
v("« 600 à 800 € » donne le milieu", p["profil"]["budget_mensuel"] == 700, p["profil"])

r = c.post(f"{B}/orientation/profil-guide", json={"reponses": {"domaine": "Droit"}})
v("un parcours incomplet redemande le champ manquant",
  r.json()["complet"] is False and r.json().get("champ_attendu") == "niveau", r.text[:160])

# --------------------------------------------------------------- fermeture

c.post(f"{B}/comptes/suppression", json={"mot_de_passe": MDP}, headers=AUTH)

print(f"\n{ok} réussis, {fail} échecs")
raise SystemExit(1 if fail else 0)
