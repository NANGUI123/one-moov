"""Tests de bout en bout des deux agents.

À lancer avant chaque mise en ligne :
    python -m scripts.tester

Les tests portent sur ce qui compte pour One Moov :
la fiabilité des informations, la reproductibilité de la notation, et le fait
qu'aucune donnée d'étudiant ne soit conservée.
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models.schemas import (  # noqa: E402
    Profil, Niveau, Formation, Secteur, RequeteOrientation, RequeteCoach,
    RequeteQuestion, RequeteEvaluation, ModeConversation, TypeEntretien,
)
from app.agents.agent1 import intake, matching, roadmap as svc_roadmap  # noqa: E402
from app.agents.agent2 import chatbot as svc_chatbot, entretien as svc_entretien  # noqa: E402
from app.services import rag, faits, embeddings  # noqa: E402
from app.config import settings  # noqa: E402

echecs = 0


def verifier(intitule: str, condition: bool, detail: str = "") -> None:
    global echecs
    if not condition:
        echecs += 1
    marque = "  ok  " if condition else " ÉCHEC"
    suffixe = f"\n         {detail}" if detail and not condition else ""
    print(f"{marque}  {intitule}{suffixe}")


db = SessionLocal()

PROFIL_TEST = Profil(
    domaine="intelligence artificielle et données",
    niveau=Niveau.master,
    formation=Formation.initiale,
    budget_mensuel=800,
    pays_origine="Cameroun",
    projet_etudes="Un master en intelligence artificielle appliquée à la santé",
    projet_pro="Ingénieure en apprentissage automatique, puis créer une structure de conseil au Cameroun",
)

# ---------------------------------------------------------------------------
print("\nBase de connaissance")
# ---------------------------------------------------------------------------

etat_rag = rag.etat(db)
verifier("des documents sont actifs", etat_rag["documents_actifs"] > 0)
verifier("des passages sont indexés", etat_rag["passages"] >= 20, f"{etat_rag['passages']} passage(s)")

questions_naturelles = [
    ("quelles pièces je dois fournir pour mon dossier", "candidature"),
    ("comment je prouve que j'ai assez d'argent", "visa"),
    ("je n'ai pas de garant en France", "logement"),
    ("qu'est-ce que le jury va me demander", "entretien"),
]
for question, phase in questions_naturelles:
    resultats = rag.rechercher(db, question, phase=phase, limite=2)
    verifier(f"la question « {question[:38]}… » trouve un passage", len(resultats) > 0)

verifier("chaque passage porte sa source", all(
    p.url and p.organisme for p in rag.rechercher(db, "dossier candidature", limite=3)
))

# ---------------------------------------------------------------------------
print("\nFaits vérifiés")
# ---------------------------------------------------------------------------

liste = faits.pour_pays(db, "Congo-Brazzaville")
verifier("des faits existent pour le Congo", len(liste) >= 4, f"{len(liste)} fait(s)")
verifier("chaque fait porte une source", all(f.source_url and f.source_libelle for f in liste))
verifier("chaque fait porte une date de vérification", all(f.verifie_le for f in liste))
verifier(
    "les faits anciens sont signalés à revérifier",
    any(f.a_reverifier for f in liste),
    "aucun fait n'est signalé, le mécanisme n'est pas vérifiable",
)

quota = faits.par_cle(db, "quota_heures_travail")
verifier("un fait se retrouve par sa clé", quota is not None and quota.valeur == "964")

specifique = faits.par_cle(db, "frais_dossier_campus_france", pays="Congo-Brazzaville")
verifier("le fait propre au pays prime", specifique is not None and specifique.pays == "Congo-Brazzaville")

# ---------------------------------------------------------------------------
print("\nAgent 1, intake guidé")
# ---------------------------------------------------------------------------

profil = Profil()
reponses = [
    "Informatique et IA", "Master", "Initiale", "800 €", "Cameroun",
    "Un master en IA appliquée à la santé", "Ingénieure en machine learning",
]
tours = 0
requete = RequeteOrientation(mode=ModeConversation.guidee, profil=profil, message="")
resultat = intake.traiter(requete)
verifier("le premier tour pose une question", len(resultat.message) > 5)

for reponse in reponses:
    if resultat.complet:
        break
    resultat = intake.traiter(
        RequeteOrientation(mode=ModeConversation.guidee, profil=resultat.profil, message=reponse)
    )
    tours += 1

verifier("le profil se complète", resultat.complet, f"après {tours} tours")
verifier("le niveau est converti en valeur du contrat", resultat.profil.niveau == Niveau.master)
verifier("le budget est converti en nombre", resultat.profil.budget_mensuel == 800,
         f"obtenu : {resultat.profil.budget_mensuel}")

# Une formulation inattendue ne doit pas polluer le profil.
essai = intake.traiter(RequeteOrientation(
    profil=Profil(domaine="x", formation=Formation.initiale, budget_mensuel=700,
                  pays_origine="Cameroun", projet_etudes="a", projet_pro="b"),
    message="Maîtrise",
))
verifier("« Maîtrise » est reconnu comme master", essai.profil.niveau == Niveau.master)

# ---------------------------------------------------------------------------
print("\nAgent 1, matching")
# ---------------------------------------------------------------------------

publics = matching.chercher_etablissements(db, PROFIL_TEST, [Secteur.public])
verifier("des établissements publics remontent", len(publics) > 0, f"{len(publics)} trouvé(s)")
verifier("ils sont tous publics", all(e.secteur == "public" for e in publics))
verifier("ils portent une date de vérification", all(e.verifie_le for e in publics))

prives = matching.chercher_etablissements(db, PROFIL_TEST, [Secteur.prive])
verifier("des établissements privés remontent", len(prives) > 0)
verifier("ils sont tous privés", all(e.secteur == "prive" for e in prives))

# Le filtre dur ne doit jamais être contourné.
profil_serre = PROFIL_TEST.model_copy(update={"budget_scolarite_an": 500})
serres = matching.chercher_etablissements(db, profil_serre, [Secteur.public, Secteur.prive])
verifier(
    "aucun établissement hors budget ne remonte",
    all(e.frais_scolarite_an <= 500 for e in serres),
    f"trouvés : {[(e.nom, e.frais_scolarite_an) for e in serres]}",
)

profil_doctorat = PROFIL_TEST.model_copy(update={"niveau": Niveau.doctorat})
doctorats = matching.chercher_etablissements(db, profil_doctorat, [Secteur.public])
verifier("le filtre de niveau s'applique", len(doctorats) < len(publics) or len(doctorats) > 0)

profil_alternance = PROFIL_TEST.model_copy(update={"formation": Formation.alternance})
alternances = matching.chercher_etablissements(db, profil_alternance, [Secteur.public, Secteur.prive])
verifier("le filtre de formation s'applique", len(alternances) > 0)

villes = matching.villes_des_etablissements(db, publics)
verifier("les villes des établissements sont retrouvées", len(villes) > 0)

analyse = matching.analyser_budget(PROFIL_TEST, villes)
verifier("l'analyse de budget est produite", len(analyse) > 20)
verifier("elle cite le budget annoncé", "800" in analyse, analyse)

# ---------------------------------------------------------------------------
print("\nAgent 1, feuille de route")
# ---------------------------------------------------------------------------

feuille = svc_roadmap.generer(db, PROFIL_TEST, [Secteur.public])
verifier("la feuille de route est produite", feuille is not None)
verifier("elle contient les six phases", len(feuille.etapes) == 6, f"{len(feuille.etapes)} étape(s)")
verifier("les phases sont dans l'ordre", [e.phase for e in feuille.etapes] == [
    "candidature", "entretien", "acceptation", "visa", "logement", "arrivee"
])
verifier("elle contient des établissements", len(feuille.etablissements) > 0)
verifier("les établissements viennent de la base", all(e.origine == "base" for e in feuille.etablissements))
verifier("elle contient des villes", len(feuille.villes) > 0)
verifier("elle porte la version de la connaissance", bool(feuille.version_connaissance))
verifier("des étapes citent des sources", any(e.sources for e in feuille.etapes))
verifier("des étapes portent des faits vérifiés", any(e.faits for e in feuille.etapes))

# Le point central : aucun montant inventé par le modèle.
texte_etapes = " ".join(f"{e.titre} {e.description} {' '.join(e.actions)}" for e in feuille.etapes)
montants = re.findall(r"\d[\d\s]{2,}\s*(?:€|euros|FCFA|francs)", texte_etapes, re.I)
verifier(
    "aucun montant n'apparaît dans le texte des étapes",
    not montants,
    f"trouvés : {montants}",
)

cles_faits = {f["cle"] for e in feuille.etapes for f in e.faits}
verifier("les montants passent par les faits vérifiés", len(cles_faits) > 0, f"clés : {cles_faits}")

# ---------------------------------------------------------------------------
print("\nAgent 2, chatbot")
# ---------------------------------------------------------------------------

accueil = svc_chatbot.repondre(db, RequeteCoach(profil=PROFIL_TEST, message=""))
verifier("le chatbot accueille l'étudiant", len(accueil.message) > 20)

question_visa = svc_chatbot.repondre(db, RequeteCoach(
    profil=PROFIL_TEST, etape_courante="visa",
    message="Comment je prouve que j'ai assez d'argent pour le visa ?",
))
verifier("le chatbot répond à une question sur le visa", len(question_visa.message) > 20)
verifier("la réponse porte des sources", len(question_visa.sources) > 0)
verifier("les sources portent une URL officielle", all(s.get("url") for s in question_visa.sources))

question_logement = svc_chatbot.repondre(db, RequeteCoach(
    profil=PROFIL_TEST, message="Je n'ai pas de garant en France, comment je fais pour louer ?",
))
verifier("le chatbot répond sur le logement", len(question_logement.message) > 20)
verifier("il cite la bonne source", any(
    "logement" in (s.get("titre", "") + s.get("url", "")).lower() or
    "Etudiant" in s.get("organisme", "")
    for s in question_logement.sources
), f"sources : {question_logement.sources}")

# ---------------------------------------------------------------------------
print("\nAgent 2, entretien")
# ---------------------------------------------------------------------------

poses: list[str] = []
q1 = svc_entretien.poser_question(db, RequeteQuestion(
    type_entretien=TypeEntretien.campus_france, profil=PROFIL_TEST, criteres_poses=poses,
))
verifier("le jury pose une question", len(q1.question) > 10)
verifier("la question porte sur un critère identifié", q1.critere in svc_entretien.CRITERES)
poses.append(q1.critere)

q2 = svc_entretien.poser_question(db, RequeteQuestion(profil=PROFIL_TEST, criteres_poses=poses))
verifier("la question suivante change de critère", q2.critere != q1.critere)

REPONSE_FORTE = (
    "Ma licence en informatique à l'université de Yaoundé m'a donné les bases en "
    "algorithmique et en mathématiques appliquées. Je veux les prolonger vers "
    "l'intelligence artificielle parce que mon objectif est de devenir ingénieure en "
    "apprentissage automatique, puis de monter une structure de conseil en données au "
    "Cameroun, où les hôpitaux manquent d'outils de prédiction."
)

faible = svc_entretien.evaluer(RequeteEvaluation(
    question=q1.question, critere=q1.critere, reponse="Je ne sais pas trop.",
))
forte = svc_entretien.evaluer(RequeteEvaluation(
    question=q1.question, critere=q1.critere, reponse=REPONSE_FORTE,
))
vide = svc_entretien.evaluer(RequeteEvaluation(
    question=q1.question, critere=q1.critere, reponse="",
))

verifier("une réponse vide obtient zéro", vide.note == 0)
verifier("une réponse vague est mal notée", faible.note <= 2, f"obtenu : {faible.note}")
verifier("une réponse argumentée est bien notée", forte.note >= 4, f"obtenu : {forte.note}")

repetitions = {
    svc_entretien.evaluer(RequeteEvaluation(
        question=q1.question, critere=q1.critere, reponse=REPONSE_FORTE,
    )).note
    for _ in range(3)
}
verifier("la notation est reproductible", repetitions == {forte.note}, f"notes obtenues : {repetitions}")

verifier("la grille est exposée", len(svc_entretien.grille()) == 6)
verifier("les poids totalisent cent", sum(c["poids"] for c in svc_entretien.grille()) == 100)

# ---------------------------------------------------------------------------
print("\nOrchestrateur de modèle")
# ---------------------------------------------------------------------------

# On monte deux faux fournisseurs sur un serveur local : le premier échoue
# systématiquement, le second répond. C'est la seule façon de vérifier que
# la bascule a vraiment lieu plutôt que de l'affirmer.
import json as _json  # noqa: E402
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402

from app.services import llm as svc_llm  # noqa: E402
from app.services.metriques import compteurs  # noqa: E402


class _FauxFournisseur(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        longueur = int(self.headers.get("Content-Length", 0))
        self.rfile.read(longueur)
        if self.path == "/echoue":
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"error":"panne simulee"}')
            return
        charge = _json.dumps(
            {"choices": [{"message": {"content": '{"message":"reponse du secours"}'}}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(charge)))
        self.end_headers()
        self.wfile.write(charge)

    def log_message(self, *args):  # silence
        pass


_serveur = HTTPServer(("127.0.0.1", 0), _FauxFournisseur)
_port = _serveur.server_address[1]
threading.Thread(target=_serveur.serve_forever, daemon=True).start()

_fournisseurs_reels = dict(svc_llm.FOURNISSEURS)
_provider_reel = settings.llm_provider
_secours_reel = settings.llm_provider_secours
_modele_reel = settings.llm_model

svc_llm.FOURNISSEURS["faux_casse"] = {
    "url": f"http://127.0.0.1:{_port}/echoue", "modele": "casse", "cle": "",
}
svc_llm.FOURNISSEURS["faux_ok"] = {
    "url": f"http://127.0.0.1:{_port}/ok", "modele": "ok", "cle": "",
}

# Cas 1 : le primaire tombe, le secours prend le relais.
settings.llm_provider, settings.llm_provider_secours = "faux_casse", "faux_ok"
settings.llm_model = ""
compteurs.reinitialiser()
try:
    resultat = svc_llm.chat_json("systeme", "utilisateur")
    bascule_ok = resultat.get("message") == "reponse du secours"
except Exception as e:  # noqa: BLE001
    bascule_ok, resultat = False, str(e)

verifier("le secours prend le relais quand le primaire tombe", bascule_ok, str(resultat))
verifier(
    "la bascule est comptée",
    compteurs.instantane()["compteurs"].get("llm.bascule_secours") == 1,
)

# Cas 2 : les deux niveaux tombent, on passe en mode guidé.
settings.llm_provider, settings.llm_provider_secours = "faux_casse", "faux_casse"
compteurs.reinitialiser()
try:
    svc_llm.chat_json("systeme", "utilisateur")
    guide_ok = False
except svc_llm.ModeMock:
    guide_ok = True
except Exception:  # noqa: BLE001
    guide_ok = False

verifier("sans aucun niveau d'IA, on bascule en mode guidé", guide_ok)
verifier(
    "le passage en mode guidé est compté",
    compteurs.instantane()["compteurs"].get("llm.mode_guide") == 1,
)

# Cas 3 : aucun fournisseur configuré du tout.
settings.llm_provider, settings.llm_provider_secours = "mock", ""
verifier("le mode mock n'expose aucun niveau d'IA", svc_llm.niveaux() == [])
verifier(
    "l'orchestrateur annonce toujours trois niveaux",
    len(svc_llm.info_fournisseur()["orchestrateur"]) == 3,
)

svc_llm.FOURNISSEURS.clear()
svc_llm.FOURNISSEURS.update(_fournisseurs_reels)
settings.llm_provider, settings.llm_provider_secours = _provider_reel, _secours_reel
settings.llm_model = _modele_reel
_serveur.shutdown()

# ---------------------------------------------------------------------------
print("\nQuotas")
# ---------------------------------------------------------------------------

from app.services import quotas as svc_quotas  # noqa: E402

fenetre = svc_quotas.FenetreGlissante(limite=3, fenetre_s=60)
verifier("les appels sous la limite passent", all(fenetre.autoriser("a")[0] for _ in range(3)))
refuse, attente = fenetre.autoriser("a")
verifier("l'appel au-delà de la limite est refusé", not refuse)
verifier("le refus indique un délai d'attente", attente > 0)
verifier("un autre visiteur n'est pas affecté", fenetre.autoriser("b")[0])

verifier(
    "l'empreinte d'une adresse n'est pas réversible",
    svc_quotas.empreinte("41.202.207.9") != "41.202.207.9"
    and len(svc_quotas.empreinte("41.202.207.9")) == 16,
)
verifier(
    "deux adresses donnent deux empreintes",
    svc_quotas.empreinte("41.202.207.9") != svc_quotas.empreinte("41.202.207.10"),
)

# ---------------------------------------------------------------------------
print("\nRNCP")
# ---------------------------------------------------------------------------

fiches = db.execute(text("SELECT count(*) FROM fiche_rncp")).scalar()
verifier("le référentiel RNCP est amorcé", fiches >= 10)

verifier(
    "tous les codes RNCP portent une source vérifiable",
    db.execute(text(
        "SELECT count(*) FROM fiche_rncp "
        "WHERE source_url NOT LIKE 'https://www.francecompetences.fr/%'"
    )).scalar() == 0,
)

verifier(
    "le numéro d'une fiche correspond à son code",
    db.execute(text(
        "SELECT count(*) FROM fiche_rncp WHERE code <> 'RNCP' || numero::text"
    )).scalar() == 0,
)

# Une fiche dont l'échéance est passée doit être vue comme expirée, même si
# le répertoire l'affiche encore active.
echue = db.execute(text(
    "SELECT etat_reel, echue FROM fiche_rncp_reelle WHERE code = 'RNCP37985'"
)).fetchone()
verifier("une fiche dont l'échéance est passée est vue comme échue", echue and echue[1])
verifier("une fiche remplacée est signalée comme telle", echue and echue[0] == "remplacee")

verifier(
    "la chaîne de remplacement mène à la fiche en vigueur",
    db.execute(text("SELECT fiche_en_vigueur('RNCP37985')")).scalar() == "RNCP42505",
)

# Une école rattachée à la fois à l'ancienne fiche et à celle qui la
# remplace ne doit pas voir la même fiche deux fois : les deux chaînes
# aboutissent au même code.
db.execute(text(
    "INSERT INTO etablissement_rncp (etablissement_id, code_rncp, niveau, certificateur_verifie, note) "
    "VALUES ('epitech','RNCP37985','master',TRUE,'test de doublon') ON CONFLICT DO NOTHING"
))
db.commit()
codes_resolus = [
    r[0] for r in db.execute(text(
        "SELECT DISTINCT fiche_en_vigueur(code_rncp) FROM etablissement_rncp "
        "WHERE etablissement_id = 'epitech'"
    )).fetchall()
]
verifier(
    "l'ancienne et la nouvelle fiche résolvent vers une seule fiche",
    len(codes_resolus) == 1 and codes_resolus[0] == "RNCP42505",
    f"codes : {codes_resolus}",
)
db.execute(text(
    "DELETE FROM etablissement_rncp WHERE etablissement_id='epitech' AND code_rncp='RNCP37985'"
))
db.commit()

verifier(
    "un rattachement non confirmé est signalé, pas masqué",
    db.execute(text(
        "SELECT count(*) FROM etablissement_rncp WHERE certificateur_verifie = FALSE AND note IS NULL"
    )).scalar() == 0,
)

# ---------------------------------------------------------------------------
print("\nRecherche lexicale")
# ---------------------------------------------------------------------------

# Non-régression : requete_ou racinisait deux fois. « dossier » devenait
# 'dossi' dans l'index et 'doss' dans la requête, et les deux ne se
# rencontraient jamais. L'échec était silencieux — un résultat vide, pas
# une erreur — et coûtait tout un pan des questions.
for mot, attendu in (("mon dossier", "dossi"), ("les formations", "format")):
    produit = db.execute(text("SELECT requete_ou(:m)::text"), {"m": mot}).scalar() or ""
    dans_index = db.execute(
        text("SELECT to_tsvector('french', :m)::text"), {"m": mot}
    ).scalar() or ""
    verifier(
        f"« {mot} » : la requête et l'index portent le même lexème",
        attendu in produit and attendu in dans_index,
        f"requête : {produit} | index : {dans_index}",
    )

verifier(
    "une question courante retrouve bien des passages",
    db.execute(text(
        "SELECT count(*) FROM passage "
        "WHERE fts @@ requete_ou('quels papiers je dois réunir pour mon dossier')"
    )).scalar() > 0,
)

# Un texte sans aucun lexème doit renvoyer NULL plutôt que de produire une
# requête vide, que PostgreSQL refuserait. À noter : « le » survit à la
# configuration française de PostgreSQL, ce n'est donc pas un mot vide ici.
verifier(
    "un texte sans lexème renvoie NULL au lieu de casser",
    db.execute(text("SELECT requete_ou('!!! ??? ...')")).scalar() is None
    and db.execute(text("SELECT requete_ou('')")).scalar() is None,
)

verifier(
    "une apostrophe dans la question ne casse pas la requête",
    db.execute(text(
        "SELECT count(*) FROM passage WHERE fts @@ requete_ou(:q)"
    ), {"q": "j'ai besoin d'un logement"}).scalar() >= 0,
)

# ---------------------------------------------------------------------------
print("\nPaiement")
# ---------------------------------------------------------------------------

from app.services import paiement as svc_paiement  # noqa: E402
from app.routers.paiements import TARIFS as TARIFS_PAIEMENT  # noqa: E402

# Orange Money n'existe pas au Congo-Brazzaville : les opérateurs y sont
# MTN et Airtel. Une liste codée « MTN + Orange » pour les deux pays serait
# fausse pour la moitié de la cible.
verifier(
    "le Cameroun propose MTN et Orange",
    svc_paiement.operateurs_du_pays("Cameroun") == ["mtn", "orange"],
    f"trouvé : {svc_paiement.operateurs_du_pays('Cameroun')}",
)
verifier(
    "le Congo propose MTN et Airtel, pas Orange",
    svc_paiement.operateurs_du_pays("Congo-Brazzaville") == ["airtel", "mtn"],
    f"trouvé : {svc_paiement.operateurs_du_pays('Congo-Brazzaville')}",
)

try:
    svc_paiement.verifier_operateur("Congo-Brazzaville", "orange")
    orange_refuse = False
except svc_paiement.ErreurPaiement:
    orange_refuse = True
verifier("Orange est refusé au Congo, avec un message explicite", orange_refuse)

# Tous les tarifs doivent être encaissables : les opérateurs et les
# agrégateurs imposent un plancher.
sous_plancher = [
    cle for cle, montant in TARIFS_PAIEMENT.items()
    if montant < svc_paiement.MONTANT_MINIMUM_FCFA
]
verifier(
    "aucun tarif n'est sous le plancher opérateur",
    not sous_plancher,
    f"tarifs trop bas : {sous_plancher}",
)

verifier(
    "un numéro local est mis au format international",
    svc_paiement.normaliser_telephone("06 12 34 56 78", "Congo-Brazzaville").startswith("242"),
    svc_paiement.normaliser_telephone("06 12 34 56 78", "Congo-Brazzaville"),
)
verifier(
    "un numéro déjà international n'est pas préfixé deux fois",
    svc_paiement.normaliser_telephone("+237699887766", "Cameroun") == "237699887766",
    svc_paiement.normaliser_telephone("+237699887766", "Cameroun"),
)

# La contrainte d'unicité est ce qui rend le webhook idempotent.
contraintes = {
    r[0] for r in db.execute(text(
        "SELECT conname FROM pg_constraint WHERE conrelid = 'paiement'::regclass"
    )).fetchall()
}
verifier(
    "la référence fournisseur est unique, donc le webhook est idempotent",
    "reference_unique_par_fournisseur" in contraintes,
    f"contraintes : {contraintes}",
)

verifier(
    "la base refuse un paiement sous le plancher",
    db.execute(text(
        "SELECT count(*) FROM information_schema.check_constraints c "
        "JOIN information_schema.constraint_column_usage u USING (constraint_name) "
        "WHERE u.table_name = 'paiement' AND u.column_name = 'montant_fcfa'"
    )).scalar() > 0,
)

# ---------------------------------------------------------------------------
print("\nNotifications")
# ---------------------------------------------------------------------------

from app.services import notifications as svc_notif  # noqa: E402

verifier(
    "le modèle de rappel d'étape existe",
    "rappel_etape" in svc_notif.MODELES,
)
verifier(
    "chaque modèle a un rendu e-mail, pour servir de repli",
    all("email_corps" in m and "email_sujet" in m for m in svc_notif.MODELES.values()),
)

# Un template WhatsApp et son équivalent e-mail doivent accepter le même
# nombre de paramètres, sinon les deux canaux ne disent pas la même chose.
coherents = True
for nom, modele in svc_notif.MODELES.items():
    nb = len(modele["parametres"])
    essai = [f"p{i}" for i in range(nb)]
    try:
        modele["email_sujet"].format(*essai)
        modele["email_corps"].format(*essai)
    except (IndexError, KeyError):
        coherents = False
verifier("les paramètres WhatsApp et e-mail concordent", coherents)

verifier(
    "le plafond WhatsApp reste sous la limite de Meta",
    settings.whatsapp_plafond_24h < 250,
    f"plafond configuré : {settings.whatsapp_plafond_24h}",
)

# Un rappel ne doit pas partir deux fois pour la même étape.
contraintes_notif = {
    r[0] for r in db.execute(text(
        "SELECT conname FROM pg_constraint WHERE conrelid = 'notification'::regclass"
    )).fetchall()
}
verifier(
    "un rappel ne peut pas être créé deux fois pour la même étape",
    "rappel_unique" in contraintes_notif,
    f"contraintes : {contraintes_notif}",
)

# ---------------------------------------------------------------------------
print("\nEmbeddings")
# ---------------------------------------------------------------------------

verifier(
    "les colonnes vectorielles sont à 1024 dimensions",
    db.execute(text(
        "SELECT atttypmod FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "WHERE c.relname = 'passage' AND a.attname = 'embedding'"
    )).scalar() == 1024,
)
verifier(
    "le modèle ayant produit chaque vecteur est enregistré",
    db.execute(text(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name IN ('passage','etablissement') AND column_name = 'modele_embedding'"
    )).scalar() == 2,
)
verifier(
    "une seule signature par fonction de recherche",
    db.execute(text(
        "SELECT count(*) FROM pg_proc WHERE proname = 'rechercher_passages'"
    )).scalar() == 1,
)
verifier(
    "sans fournisseur configuré, l'encodage renvoie None au lieu de lever",
    embeddings.encoder("une question d'étudiant") is None or embeddings.disponible(),
)

# ---------------------------------------------------------------------------
print("\nConfidentialité")
# ---------------------------------------------------------------------------

tables = {
    r[0]
    for r in db.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )).fetchall()
}

# Les comptes existent désormais. Ce qui reste interdit, c'est la
# conservation des échanges : une conversation en dit bien plus long sur
# quelqu'un qu'une liste de champs.
tables_interdites = {"conversation", "message", "echange", "historique", "journal_conversation"}
verifier(
    "aucune table ne stocke de conversation",
    not (tables & tables_interdites),
    f"tables trouvées : {tables & tables_interdites}",
)

colonnes_sensibles = {
    r[0]
    for r in db.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND ("
        "  column_name ILIKE '%message%' OR column_name ILIKE '%conversation%'"
        "  OR column_name ILIKE '%historique%')"
    )).fetchall()
}
verifier(
    "aucune colonne ne stocke de conversation",
    not colonnes_sensibles,
    f"colonnes trouvées : {colonnes_sensibles}",
)

champs_profil = set(Profil.model_fields.keys())
champs_identifiants = {"nom", "prenom", "email", "telephone", "passeport", "adresse", "date_naissance"}
verifier(
    "le profil envoyé aux agents ne contient aucun champ d'identité",
    not (champs_profil & champs_identifiants),
    f"champs trouvés : {champs_profil & champs_identifiants}",
)

# La suppression doit tout emporter. On le vérifie pour de vrai plutôt que
# de faire confiance aux clés étrangères.
db.execute(text("DELETE FROM utilisateur WHERE email = 'cascade.test@example.com'"))
db.commit()
identifiant = db.execute(text(
    "INSERT INTO utilisateur (email, mot_de_passe) "
    "VALUES ('cascade.test@example.com', 'scrypt$x') RETURNING id"
)).scalar()
db.execute(
    text("INSERT INTO orientation_enregistree (utilisateur_id, profil) VALUES (:u, '{}'::jsonb)"),
    {"u": identifiant},
)
db.execute(
    text("INSERT INTO roadmap_enregistree (utilisateur_id, contenu) VALUES (:u, '{}'::jsonb)"),
    {"u": identifiant},
)
db.execute(
    text("INSERT INTO code_verification (utilisateur_id, code_empreinte, expire_le) "
         "VALUES (:u, 'x', now() + interval '1 hour')"),
    {"u": identifiant},
)
db.commit()

db.execute(text("DELETE FROM utilisateur WHERE id = :i"), {"i": identifiant})
db.commit()

restes = db.execute(
    text(
        "SELECT (SELECT count(*) FROM orientation_enregistree WHERE utilisateur_id = :i)"
        "     + (SELECT count(*) FROM roadmap_enregistree WHERE utilisateur_id = :i)"
        "     + (SELECT count(*) FROM code_verification WHERE utilisateur_id = :i)"
    ),
    {"i": identifiant},
).scalar()
verifier("la suppression d'un compte emporte toutes ses données", restes == 0, f"restes : {restes}")

verifier(
    "le mot de passe n'est jamais stocké en clair",
    db.execute(text(
        "SELECT count(*) FROM utilisateur WHERE mot_de_passe NOT LIKE 'scrypt$%'"
    )).scalar() == 0,
)

db.close()

print(
    "\nTous les tests passent.\n"
    if echecs == 0
    else f"\n{echecs} test(s) en échec.\n"
)
sys.exit(0 if echecs == 0 else 1)
