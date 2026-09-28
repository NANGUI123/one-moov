"""Configuration de l'application, lue depuis l'environnement.

Aucune clé n'est écrite en dur. En développement, elles viennent d'un
fichier .env ignoré par git. En production, ce sont des variables
d'environnement de la plateforme d'hébergement.
"""

import secrets

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Base de données ---
    database_url: str = "postgresql+psycopg2://onemoov:onemoov@localhost:5432/onemoov"

    # --- Orchestrateur de modèle de langage ---
    # Niveau 1, le primaire : huggingface | groq | openai | mistral | ollama | mock
    llm_provider: str = "gemini"
    # Niveau 2, le secours : bascule automatique si le primaire échoue.
    # Laisser vide pour n'avoir qu'un seul niveau d'IA.
    llm_provider_secours: str = "mistral"
    # Ne s'applique qu'au primaire : le secours garde son propre modèle.
    llm_model: str = ""
    llm_timeout: float = 60.0

    # --- Un fournisseur par fonction ---
    #
    # Les trois usages du modèle n'ont pas les mêmes exigences, et les tenir
    # séparés permet de changer l'un sans toucher aux autres.
    #
    #   orientation  Ne sert qu'au mode libre : le mode guidé n'appelle aucun
    #                modèle. Un modèle rapide suffit, il extrait des champs
    #                d'un récit.
    #
    #   roadmap      C'est le livrable payé. Le modèle rédige les étapes à
    #                partir des passages du RAG, et aucun montant ni délai ne
    #                passe par lui : ils viennent de la base. La qualité de
    #                rédaction prime sur la latence, l'étudiant attend
    #                quelques secondes une seule fois.
    #
    #   chatbot      Interactif, donc la latence compte autant que la
    #                qualité. Il doit surtout rester collé aux passages
    #                fournis plutôt que broder.
    #
    # Laisser vide pour suivre llm_provider. Le niveau de secours, lui, est
    # commun aux trois : une panne de fournisseur ne connaît pas nos
    # fonctions.
    llm_provider_orientation: str = ""
    llm_modele_orientation: str = ""
    llm_provider_roadmap: str = ""
    llm_modele_roadmap: str = ""
    llm_provider_chatbot: str = ""
    llm_modele_chatbot: str = ""

    huggingface_api_key: str = ""
    groq_api_key: str = ""
    openai_api_key: str = ""
    mistral_api_key: str = ""
    gemini_api_key: str = ""

    # --- Embeddings ---
    #
    # mistral | openai | local
    #
    # Par API, et non en local : un modèle multilingue occupe ~384 Mo de RAM
    # rien que pour sa table de vocabulaire, avec un pic au double au
    # chargement. Cela ne tient pas dans les 512 Mo du plan d'hébergement,
    # et passer au plan à 7 $ n'y change rien — il a aussi 512 Mo.
    #
    # « mistral » vise l'endpoint européen : embedder la question d'un
    # étudiant l'envoie à un tiers, et un sous-traitant européen est plus
    # simple à justifier au regard de la loi camerounaise n° 2024/017.
    #
    # « local » reste utile pour embedder le corpus hors ligne, sur une
    # machine qui a la RAM.
    #
    # ATTENTION : changer de fournisseur impose de ré-embedder TOUT le
    # corpus. Les vecteurs de deux modèles vivent dans des espaces sans
    # rapport, et la recherche renvoie du bruit sans lever d'erreur.
    embeddings_fournisseur: str = "mistral"
    embeddings_enabled: bool = False
    embeddings_timeout: float = 20.0
    embeddings_taille_lot: int = 64

    # --- RAG ---
    rag_top_k: int = 5          # passages renvoyés à l'agent
    rag_candidats: int = 20     # candidats par méthode avant fusion
    rag_rrf_k: int = 60         # constante de la fusion RRF

    # --- Comptes ---
    # Le secret signe les jetons. S'il change, tous les jetons émis sont
    # invalidés et les étudiants doivent se reconnecter — ce qui est le
    # comportement voulu en cas de fuite. En production, il DOIT être posé
    # explicitement : un secret tiré au hasard déconnecterait tout le monde
    # à chaque redémarrage.
    jwt_secret: str = ""
    jwt_duree_heures: int = 72
    # Durée de vie d'un code de vérification envoyé par e-mail.
    verification_duree_minutes: int = 30

    # --- Envoi des e-mails de vérification ---
    # Sans SMTP configuré, le code est écrit dans les journaux du serveur au
    # lieu d'être envoyé. Utilisable en démonstration, jamais en production.
    smtp_hote: str = ""
    smtp_port: int = 587
    smtp_utilisateur: str = ""
    smtp_motdepasse: str = ""
    smtp_expediteur: str = "One Moov <ne-pas-repondre@one-moov.app>"

    # --- Quotas et anti-abus ---
    #
    # Calibré sur un usage réel, pas sur une intuition : en orientation
    # guidée, l'étudiant enchaîne sept réponses en une trentaine de
    # secondes, puis génère sa feuille de route, puis pose des questions au
    # chatbot, puis passe dix questions d'entretien qui coûtent deux appels
    # chacune. Une limite trop basse punit l'étudiant assidu et laisse
    # passer le robot, qui lui tape des centaines d'appels par minute.
    quota_rafale: int = 40            # appels par minute et par visiteur
    quota_horaire: int = 400          # appels par heure et par visiteur
    quota_modele_horaire: int = 120   # appels à l'IA par heure et par visiteur
    # Sel des empreintes de quotas. Tiré au hasard s'il n'est pas posé :
    # les empreintes ne se recoupent alors pas d'un déploiement à l'autre.
    sel_quotas: str = ""

    # --- Paiement mobile money ---
    # pawapay | manuel | mock
    #
    # pawapay est le seul agrégateur qui couvre à la fois le Cameroun
    # (MTN, Orange) et le Congo-Brazzaville (MTN, Airtel). CinetPay ne
    # couvre pas le Congo, et Orange Money n'y existe pas.
    #
    # « manuel » : l'étudiant paie sur un numéro marchand existant et saisit
    # sa référence, un administrateur valide. C'est le mode de lancement
    # quand l'onboarding de l'agrégateur n'est pas terminé.
    paiement_fournisseur: str = "manual"
    pawapay_token: str = ""
    pawapay_sandbox: bool = True
    # La signature des webhooks pawaPay est OPTIONNELLE et désactivée par
    # défaut : il faut l'activer dans le tableau de bord. Sans elle, le
    # webhook reste un simple déclencheur — le statut vient de l'API.
    pawapay_signature_secret: str = ""
    # Affiché à l'étudiant en mode manuel.
    paiement_numero_marchand: str = ""

    # --- Notifications ---
    #
    # mock | twilio | meta
    #
    # « twilio » est le chemin praticable pour une mise en service rapide. Son
    # bac à sable WhatsApp s'active en cinq minutes : l'étudiant envoie « join
    # <code> » au numéro de test, et il peut recevoir des messages. Dans les
    # 24 heures qui suivent un message entrant, le texte est libre — aucun
    # template à faire approuver. C'est ce qui permet une démonstration
    # aujourd'hui plutôt que dans trois semaines.
    #
    # « meta » est l'API Cloud officielle, et la cible en production : un
    # numéro d'entreprise, des templates approuvés, pas de ré-inscription des
    # destinataires tous les trois jours. C'est le seul moyen d'envoyer un
    # rappel hors fenêtre de 24 heures, ce dont un rappel d'échéance a
    # justement besoin.
    #
    # Les deux coexistent parce qu'ils ne servent pas le même moment du
    # projet, et que basculer de l'un à l'autre ne doit pas demander de
    # réécrire l'envoi.
    notifications_fournisseur: str = "twilio"
    # Conservé pour compatibilité : un « true » ici force le mode mock quel que
    # soit le fournisseur choisi.
    notifications_mock: bool = False

    # Meta Cloud API
    whatsapp_token: str = ""
    whatsapp_numero_id: str = ""
    whatsapp_version_api: str = "v21.0"

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    # Le numéro expéditeur, au format international sans le préfixe
    # « whatsapp: », qui est ajouté par le code. Le bac à sable Twilio utilise
    # +14155238886, partagé entre tous les comptes d'essai.
    twilio_numero: str = "+14155238886"
    # Les limites d'un compte d'essai, qui ne sont pas des choix mais des
    # contraintes du fournisseur : un message toutes les trois secondes, une
    # cinquantaine par jour, et chaque destinataire doit renvoyer « join
    # <code> » tous les trois jours pour rester joignable.
    twilio_essai: bool = True
    # Meta limite à 250 destinataires uniques par 24 h tant que l'entreprise
    # n'est pas vérifiée. On s'arrête avant, plutôt que de laisser l'API
    # refuser : dépasser dégrade la note de qualité du numéro.
    whatsapp_plafond_24h: int = 240

    # --- RNCP ---
    # Jeu de données ouvert France Compétences, mis à jour quotidiennement.
    rncp_export_url: str = "https://www.data.gouv.fr/api/1/datasets/r/05d4f5d8-31f4-4420-9a61-4ed56d70cf1c"
    rncp_fiche_url: str = "https://www.francecompetences.fr/recherche/rncp/{numero}/"

    # --- Sécurité ---
    origines_autorisees: str = "http://localhost:5173,https://one-moov.pages.dev"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

# Un secret de jetons absent est tolérable en développement, jamais en
# production. On en tire un au hasard pour que l'application démarre, et on
# le signale bruyamment : les jetons ne survivront pas au redémarrage.
JWT_SECRET_EPHEMERE = not settings.jwt_secret
if JWT_SECRET_EPHEMERE:
    settings.jwt_secret = secrets.token_urlsafe(48)
