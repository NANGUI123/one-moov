"""Parcours complet d'un compte, par HTTP.

    python -m scripts.tester_comptes

Suppose l'API lancée en local et SMTP non configuré : le code de
vérification est alors écrit dans le journal du serveur, que ce script
relit. Passer le chemin du journal par la variable JOURNAL.
"""
import os, re, subprocess, sys
import httpx

B = "http://127.0.0.1:8000/api"
EMAIL = "etudiante.test@example.com"
MDP = "une phrase de passe correcte"
ok = fail = 0

def v(nom, cond, detail=""):
    global ok, fail
    if cond: ok += 1; print(f"  ok    {nom}")
    else: fail += 1; print(f"  ECHEC {nom} {detail}")

class ClientTeste(httpx.Client):
    """Client qui s'arrête net sur un refus de quota.

    Ce script enchaîne une vingtaine d'appels en quelques secondes, bien
    plus vite qu'un étudiant. Il touche donc le quota anti-rafale, qui est
    lui-même testé ailleurs (scripts/tester.py). Plutôt que d'échouer sur
    une erreur incompréhensible, on le dit.
    """

    def request(self, *args, **kwargs):
        reponse = super().request(*args, **kwargs)
        if reponse.status_code == 429:
            print(
                "\nLe quota anti-rafale a coupé le test — c'est normal, il "
                "tape bien plus vite qu'un humain.\n"
                "Relance l'API avec des quotas de test :\n"
                "  QUOTA_RAFALE=500 QUOTA_HORAIRE=5000 QUOTA_MODELE_HORAIRE=3000 ./lancer_dev.sh\n"
            )
            raise SystemExit(2)
        return reponse


c = ClientTeste(timeout=30)

# Nettoyage préalable
subprocess.run(["su","postgres","-c",
    f"psql -d onemoov -c \"DELETE FROM utilisateur WHERE email='{EMAIL}'\""],
    capture_output=True)

print("\nInscription et vérification")
r = c.post(f"{B}/comptes/inscription", json={"email": EMAIL, "mot_de_passe": MDP, "pays": "Congo-Brazzaville"})
v("l'inscription est acceptée", r.status_code == 201, r.text[:120])
v("la réponse ne confirme pas l'existence du compte",
  "peut être utilisée" in r.json().get("message",""))

r2 = c.post(f"{B}/comptes/inscription", json={"email": EMAIL, "mot_de_passe": MDP, "pays": "Congo-Brazzaville"})
v("une adresse déjà prise donne la même réponse",
  r2.status_code == 201 and r2.json()["message"] == r.json()["message"])

r = c.post(f"{B}/comptes/inscription", json={"email":"x@example.com","mot_de_passe":"court", "pays": "Congo-Brazzaville"})
v("un mot de passe trop court est refusé", r.status_code == 422)

# Le code est dans les journaux (SMTP non configuré)
journal = open(os.environ.get("JOURNAL", "/tmp/onemoov-api.log")).read()
codes = re.findall(rf"code de vérification de {re.escape(EMAIL)} est (\d{{6}})", journal)
v("un code a été émis", bool(codes))
code = codes[-1] if codes else "000000"

r = c.post(f"{B}/comptes/verification", json={"email": EMAIL, "code": "999999"})
v("un mauvais code est refusé", r.status_code == 400)

r = c.post(f"{B}/comptes/verification", json={"email": EMAIL, "code": code})
v("le bon code ouvre la session", r.status_code == 200, r.text[:120])
jeton = r.json().get("jeton","")
v("un jeton est délivré", len(jeton) > 40)

r = c.post(f"{B}/comptes/verification", json={"email": EMAIL, "code": code})
v("un code déjà utilisé ne vaut plus rien", r.status_code == 400)

print("\nConnexion")
r = c.post(f"{B}/comptes/connexion", json={"email": EMAIL, "mot_de_passe": "mauvais mot de passe"})
v("un mauvais mot de passe est refusé", r.status_code == 401)
v("le refus ne dit pas si le compte existe", r.json()["detail"] == "Connexion impossible.")

r = c.post(f"{B}/comptes/connexion", json={"email":"inconnu@example.com","mot_de_passe":MDP})
v("un compte inexistant donne le même refus", r.json()["detail"] == "Connexion impossible.")

r = c.post(f"{B}/comptes/connexion", json={"email": EMAIL, "mot_de_passe": MDP, "pays": "Congo-Brazzaville"})
v("la connexion réussit", r.status_code == 200)
jeton = r.json()["jeton"]
entetes = {"Authorization": f"Bearer {jeton}"}

print("\nJetons")
v("sans jeton, /moi refuse", c.get(f"{B}/comptes/moi").status_code == 401)
v("un jeton bidon est refusé",
  c.get(f"{B}/comptes/moi", headers={"Authorization":"Bearer n.importe.quoi"}).status_code == 401)
# Jeton signé avec un autre secret
import jwt as _jwt
faux = _jwt.encode({"sub":"00000000-0000-0000-0000-000000000000","iss":"one-moov"}, "mauvais-secret", algorithm="HS256")
v("un jeton signé ailleurs est refusé",
  c.get(f"{B}/comptes/moi", headers={"Authorization": f"Bearer {faux}"}).status_code == 401)

print("\nSauvegarde et relecture")
profil = {"domaine":"Informatique et IA","niveau":"master","budget_mensuel":800,"pays_origine":"Cameroun"}
roadmap = {"resume":"test","etapes":[{"ordre":1,"titre":"Dossier","phase":"candidature"}]}
r = c.put(f"{B}/comptes/sauvegarde", headers=entetes, json={
    "profil": profil, "roadmap": roadmap,
    "etapes_faites":[0], "secteurs_payes":["public"], "chatbot_ouvert": True})
v("la sauvegarde est acceptée", r.status_code == 200, r.text[:120])

r = c.get(f"{B}/comptes/moi", headers=entetes)
d = r.json()
v("le profil est relu à l'identique", d["profil"] == profil)
v("la feuille de route est relue à l'identique", d["roadmap"] == roadmap)
v("la progression est conservée", d["etapes_faites"] == [0])
v("le chatbot reste débloqué", d["chatbot_ouvert"] is True)

r = c.put(f"{B}/comptes/sauvegarde", headers=entetes, json={
    "profil": {**profil, "budget_mensuel": 950}, "etapes_faites":[0,1]})
v("une sauvegarde partielle ne perd pas la feuille de route",
  c.get(f"{B}/comptes/moi", headers=entetes).json()["roadmap"] == roadmap)

print("\nAucune conversation enregistrée")
sortie = subprocess.run(["su","postgres","-c",
    "psql -d onemoov -tAc \"SELECT table_name||'.'||column_name FROM information_schema.columns "
    "WHERE table_schema='public' AND (column_name ILIKE '%message%' OR column_name ILIKE '%conversation%' "
    "OR column_name ILIKE '%historique%')\""], capture_output=True, text=True)
v("aucune colonne ne stocke de conversation", not sortie.stdout.strip(), sortie.stdout[:200])

sortie = subprocess.run(["su","postgres","-c",
    "psql -d onemoov -tAc \"SELECT mot_de_passe FROM utilisateur WHERE email='%s'\"" % EMAIL],
    capture_output=True, text=True)
v("le mot de passe n'est pas stocké en clair", MDP not in sortie.stdout)
v("l'empreinte est bien du scrypt", sortie.stdout.strip().startswith("scrypt$"))

# L'identifiant est relevé avant la suppression : après, il n'existe plus.
identifiant = subprocess.run(["su","postgres","-c",
    "psql -d onemoov -tAc \"SELECT id FROM utilisateur WHERE email='%s'\"" % EMAIL],
    capture_output=True, text=True).stdout.strip()

print("\nDroit à la suppression")
r = c.post(f"{B}/comptes/suppression", headers=entetes, json={"mot_de_passe":"mauvais"})
v("la suppression exige le bon mot de passe", r.status_code == 401)

r = c.post(f"{B}/comptes/suppression", headers=entetes, json={"mot_de_passe": MDP})
v("la suppression réussit", r.status_code == 200, r.text[:120])

# On compte les restes DE CE COMPTE, pas toutes les lignes des tables :
# d'autres comptes peuvent exister, et un compteur global ne dirait rien
# de la cascade qu'on veut vérifier.
reste = subprocess.run(["su","postgres","-c",
    "psql -d onemoov -tAc \"SELECT (SELECT count(*) FROM utilisateur WHERE email='%s')"
    "+(SELECT count(*) FROM orientation_enregistree WHERE utilisateur_id='%s')"
    "+(SELECT count(*) FROM roadmap_enregistree WHERE utilisateur_id='%s')"
    "+(SELECT count(*) FROM code_verification WHERE utilisateur_id='%s')\""
    % (EMAIL, identifiant, identifiant, identifiant)],
    capture_output=True, text=True)
v("plus aucune trace de ce compte en base", reste.stdout.strip() == "0", reste.stdout[:80])
v("le jeton ne vaut plus rien après suppression",
  c.get(f"{B}/comptes/moi", headers=entetes).status_code == 401)

print(f"\n{ok} réussis, {fail} échecs")
sys.exit(1 if fail else 0)
