"""Vérifie que les clés posées marchent vraiment, avant de s'y fier.

    python -m scripts.verifier_cles

Pourquoi ce script existe
-------------------------
Une clé valide ne garantit pas qu'un modèle réponde. Les fournisseurs
retirent des modèles de leur palier gratuit sans prévenir : Groq a sorti
llama-3.3-70b-versatile du sien le 16 août 2026. Le symptôme est trompeur —
l'orchestrateur bascule sur le secours et tout paraît fonctionner, en plus
lent et en plus cher, alors que le problème est un nom de modèle périmé.

Ce script pose donc trois questions à chaque fournisseur, dans cet ordre :

    1. La clé est-elle acceptée ?
    2. Le modèle configuré figure-t-il parmi ceux que cette clé peut voir ?
    3. Répond-il vraiment, en JSON, sur un appel minuscule ?

La troisième est la seule qui compte. Les deux premières servent à dire où ça
casse quand la troisième échoue.

Le cas des embeddings
---------------------
La dimension du vecteur est vérifiée contre le schéma. Se tromper de modèle
d'embeddings ne lève aucune erreur : la recherche renvoie du bruit, en
silence. C'est le genre de défaut qu'on ne découvre qu'en mesurant, et la
colonne est déclarée vector(1024).
"""

from __future__ import annotations

import pathlib
import sys

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.services import embeddings as svc_emb  # noqa: E402
from app.services import llm  # noqa: E402
from app.services import notifications as svc_notif  # noqa: E402

DIMENSION_ATTENDUE = 1024   # ce que déclare le schéma, migrations 001 et 003

VERT, ROUGE, JAUNE, GRIS, FIN = "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[0m"

problemes: list[str] = []


def ligne(etat: str, texte: str, detail: str = "") -> None:
    couleurs = {"ok": VERT, "ko": ROUGE, "vide": GRIS, "attention": JAUNE}
    marques = {"ok": "ok  ", "ko": "ECHEC", "vide": "--  ", "attention": "!   "}
    c = couleurs.get(etat, "")
    print(f"  {c}{marques.get(etat, '')}{FIN} {texte}")
    if detail:
        print(f"         {GRIS}{detail}{FIN}")


def modeles_visibles(base_url: str, cle: str) -> list[str] | str:
    """La liste des modèles que cette clé peut voir, ou le motif du refus."""
    url = base_url.replace("/chat/completions", "/models").replace("/embeddings", "/models")
    try:
        with httpx.Client(timeout=20) as client:
            r = client.get(url, headers={"Authorization": f"Bearer {cle}"})
    except httpx.RequestError as e:
        return f"injoignable : {e}"

    if r.status_code == 401:
        return "clé refusée (401)"
    if r.status_code >= 400:
        return f"HTTP {r.status_code} : {r.text[:120]}"

    try:
        return [m["id"] for m in r.json().get("data", [])]
    except (ValueError, KeyError, TypeError):
        return "réponse illisible"


def verifier_modele(nom: str, url: str, modele: str, cle: str) -> None:
    print(f"\n{nom} — modèle configuré : {modele}")

    visibles = modeles_visibles(url, cle)
    if isinstance(visibles, str):
        ligne("ko", "la clé n'ouvre pas la liste des modèles", visibles)
        problemes.append(f"{nom} : {visibles}")
        return

    ligne("ok", f"clé acceptée, {len(visibles)} modèle(s) accessible(s)")

    # Le routeur Hugging Face publie ses modèles sous la forme
    # « meta-llama/Llama-3.3-70B-Instruct:together », le suffixe nommant
    # l'hébergeur qui sert réellement. On compare sur la partie utile, sinon
    # un modèle parfaitement disponible serait déclaré introuvable.
    racines = {m.split(":")[0] for m in visibles}

    if modele.split(":")[0] not in racines:
        proches = [m for m in visibles if "embed" not in m and "whisper" not in m][:6]
        ligne("ko", f"« {modele} » n'est pas dans la liste de cette clé",
              "Disponibles : " + ", ".join(proches) if proches else "aucun modèle de chat")
        problemes.append(
            f"{nom} : le modèle « {modele} » est hors de portée de cette clé. "
            f"Poser LLM_MODEL (ou LLM_MODELE_<FONCTION>) sur l'un de : {', '.join(proches)}"
        )
        return

    ligne("ok", "le modèle figure bien dans la liste")

    # Le seul test qui compte : un vrai appel, en JSON.
    try:
        with httpx.Client(timeout=45) as client:
            r = client.post(
                url,
                headers={"Authorization": f"Bearer {cle}", "Content-Type": "application/json"},
                json={
                    "model": modele,
                    "messages": [
                        {"role": "system", "content": "Réponds uniquement par du JSON."},
                        {"role": "user", "content": '{"tache": "renvoie {\\"ok\\": true}"}'},
                    ],
                    "temperature": 0,
                    "max_tokens": 40,
                    "response_format": {"type": "json_object"},
                },
            )
    except httpx.RequestError as e:
        ligne("ko", "appel impossible", str(e))
        problemes.append(f"{nom} : {e}")
        return

    if r.status_code == 429:
        ligne("attention", "quota du fournisseur atteint",
              "La clé est bonne. Réessayer dans une minute.")
        return
    if r.status_code == 402:
        # Hugging Face surtout : son palier gratuit est un crédit mensuel de
        # 0,10 $, pas un quota de requêtes. Il s'épuise sans prévenir.
        ligne("ko", "crédit épuisé chez le fournisseur",
              "La clé est bonne, le compte n'a plus de crédit. C'est une "
              "facture, pas une panne. Recharger, ou changer de fournisseur "
              "pour cette fonction.")
        problemes.append(f"{nom} : crédit épuisé (HTTP 402)")
        return
    if r.status_code >= 400:
        ligne("ko", f"le modèle a refusé l'appel (HTTP {r.status_code})", r.text[:200])
        problemes.append(f"{nom} : HTTP {r.status_code} sur un appel réel")
        return

    try:
        contenu = r.json()["choices"][0]["message"]["content"]
        llm.parser_json(contenu)
    except Exception as e:  # noqa: BLE001
        ligne("attention", "le modèle répond mais pas en JSON exploitable", str(e)[:150])
        problemes.append(f"{nom} : sortie JSON douteuse, à surveiller")
        return

    ligne("ok", "appel réel réussi, sortie JSON valide")


def verifier_embeddings() -> None:
    print("\nEmbeddings")

    if not settings.embeddings_enabled:
        ligne("vide", "désactivés (EMBEDDINGS_ENABLED=false)",
              "La recherche fonctionne en plein texte français seul.")
        return

    f = svc_emb.FOURNISSEURS.get(settings.embeddings_fournisseur)
    if not f:
        ligne("ko", f"fournisseur inconnu : {settings.embeddings_fournisseur}")
        problemes.append("Embeddings : fournisseur inconnu")
        return

    vecteur = svc_emb.encoder("Test de vérification des embeddings.")
    if vecteur is None:
        # encoder() ne lève jamais : il renvoie None et la recherche retombe
        # en plein texte. C'est le bon comportement en production, et
        # exactement ce qui rend la panne invisible. D'où ce script.
        ligne("ko", "aucun vecteur renvoyé",
              "Clé absente, refusée, quota atteint, ou réponse illisible — la ligne "
              "juste au-dessus dit laquelle. La recherche retombe en plein texte "
              "sans lever d'erreur, donc rien ne le signalerait par ailleurs.")
        problemes.append("Embeddings : activés mais inopérants")
        return

    ligne("ok", f"{settings.embeddings_fournisseur} répond")

    if len(vecteur) != DIMENSION_ATTENDUE:
        ligne("ko", f"dimension {len(vecteur)}, le schéma en attend {DIMENSION_ATTENDUE}",
              "La recherche renverrait du bruit sans lever d'erreur. "
              "Changer de modèle, ou migrer la colonne et ré-embedder tout le corpus.")
        problemes.append(
            f"Embeddings : dimension {len(vecteur)} contre {DIMENSION_ATTENDUE} attendus"
        )
        return

    ligne("ok", f"dimension {len(vecteur)}, conforme au schéma")


def verifier_twilio() -> None:
    print("\nWhatsApp")

    fournisseur = svc_notif.fournisseur_whatsapp()
    if fournisseur == "mock":
        ligne("vide", "en mode simulé",
              "Les envois sont écrits dans les journaux. Poser NOTIFICATIONS_FOURNISSEUR "
              "et les clés correspondantes pour envoyer vraiment.")
        return

    if fournisseur == "meta":
        ligne("ok", "Meta Cloud API configurée",
              "Vérifier que les templates rappel_etape et valeur_a_reverifier sont approuvés.")
        return

    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.twilio_account_sid}.json"
    )
    try:
        with httpx.Client(timeout=20) as client:
            r = client.get(url, auth=(settings.twilio_account_sid, settings.twilio_auth_token))
    except httpx.RequestError as e:
        ligne("ko", "Twilio injoignable", str(e))
        problemes.append(f"Twilio : {e}")
        return

    if r.status_code >= 400:
        ligne("ko", f"identifiants refusés (HTTP {r.status_code})", r.text[:150])
        problemes.append("Twilio : identifiants refusés")
        return

    compte = r.json()
    ligne("ok", f"compte Twilio « {compte.get('friendly_name', '?')} », "
                f"statut {compte.get('status', '?')}")

    if compte.get("type") == "Trial" and not settings.twilio_essai:
        ligne("attention", "compte d'essai, mais TWILIO_ESSAI=false",
              "Les plafonds d'essai ne seront pas respectés : les envois en excès "
              "reviendront en erreur 20429.")
        problemes.append("Twilio : TWILIO_ESSAI devrait valoir true")
    elif compte.get("type") == "Trial":
        ligne("ok", "compte d'essai reconnu, plafonds respectés",
              f"45 messages par jour, un toutes les 3,2 s, depuis {settings.twilio_numero}. "
              "Chaque destinataire doit envoyer « join <code> » tous les trois jours.")


def main() -> None:
    print("\nVérification des clés\n" + "=" * 60)

    vus = set()
    for fonction in (None,) + llm.FONCTIONS:
        primaire, modele = llm._reglage(fonction)
        for nom, voulu in ((primaire, modele), (settings.llm_provider_secours, "")):
            resolu = llm._resoudre(nom, voulu)
            if not resolu:
                continue
            if resolu[:3] in vus:
                continue
            vus.add(resolu[:3])
            verifier_modele(resolu[0], resolu[1], resolu[2], resolu[3])

    if not vus:
        print("\nModèles de langage")
        ligne("vide", "aucune clé posée",
              "L'application tourne en mode guidé : questionnaire à choix, réponses "
              "du chatbot sans reformulation, entretien noté sur grille. "
              "Démontrable tel quel.")

    verifier_embeddings()
    verifier_twilio()

    print("\n" + "=" * 60)
    if problemes:
        print(f"{ROUGE}{len(problemes)} point(s) à régler :{FIN}")
        for p in problemes:
            print(f"  - {p}")
        raise SystemExit(1)

    print(f"{VERT}Tout ce qui est configuré répond.{FIN}\n")


if __name__ == "__main__":
    main()
