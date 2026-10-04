"""
config.py — Configuration centralisée (lue depuis l'environnement / .env).
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Base de données — vide => SQLite local (démarre sans rien installer)
    DATABASE_URL: str = ""

    # LLM — niveau 1, le fournisseur nominal
    #
    # L'ordre des modèles est l'ordre d'essai. llama-3.3-70b-versatile a quitté
    # le palier gratuit de Groq le 16 août 2026 : le laisser en tête faisait
    # payer un échec à chaque requête avant de réussir sur le second.
    GROQ_API_KEY: str = ""
    GROQ_MODELS: str = "llama-3.1-8b-instant,llama-3.3-70b-versatile"
    GROQ_MODEL_LEGER: str = "llama-3.1-8b-instant"

    # LLM — niveau 2, le secours, DÉLIBÉRÉMENT chez un autre hébergeur
    #
    # Deux modèles chez un même fournisseur tombent ensemble : une panne de
    # l'hébergeur les emporte tous les deux. Ce niveau n'existe que pour
    # couvrir ce cas. Sans clé, il est simplement sauté et le mode guidé
    # reste le dernier recours.
    SECOURS_API_KEY: str = ""
    SECOURS_BASE_URL: str = "https://api.mistral.ai/v1"
    SECOURS_MODELS: str = "mistral-small-latest"

    # Sécurité
    JWT_SECRET: str = "change-me-in-production"
    JWT_EXPIRE_HOURS: int = 720

    # Tarification
    PRIX_PARCOURS_EUR: float = 80.0
    TAUX_EUR_FCFA: float = 655.957

    # Paiement CinetPay
    CINETPAY_API_KEY: str = ""
    CINETPAY_SITE_ID: str = ""
    CINETPAY_MODE: str = "SANDBOX"
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # France Compétences
    FRANCE_COMPETENCES_BASE: str = "https://api.francecompetences.fr"

    # Vérification RNCP par LLM connecté au web (point 8).
    # OpenAI-compatible : par défaut Perplexity (modèles « sonar », accès internet).
    # Sans clé → repli sur l'export officiel synchronisé localement.
    RNCP_LLM_API_KEY: str = ""
    RNCP_LLM_BASE_URL: str = "https://api.perplexity.ai"
    RNCP_LLM_MODEL: str = "sonar"

    # Vérification e-mail + envoi (SMTP via Brevo recommandé). Sans
    # SMTP_HOST → mode démo (lien affiché).
    #
    # Configuration Brevo (ex-Sendinblue), 300 e-mails/j gratuits :
    #   SMTP_HOST=smtp-relay.brevo.com
    #   SMTP_PORT=587
    #   SMTP_USER=<login SMTP Brevo, format email>
    #   SMTP_PASSWORD=<clé SMTP Brevo — pas ton mot de passe compte>
    EMAIL_VERIFICATION_REQUISE: bool = True
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "One Moov <no-reply@onemoov.app>"
    SMTP_TLS: bool = True

    # WhatsApp Business API via Twilio.
    # Sandbox actif en 5 min (l'étudiant envoie « join <code> » au numéro
    # de test). En production : numéro d'entreprise + templates Meta.
    # Sans TWILIO_ACCOUNT_SID → mode démo : le rappel est loggé, pas envoyé.
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"   # sandbox partagé Twilio
    # SID du template Meta approuvé pour les rappels J-3, requis pour envoyer
    # HORS de la fenêtre de 24 h. Vide → mode libre 24 h uniquement (dev).
    TWILIO_RAPPEL_TEMPLATE_SID: str = ""

    # Garde-fous
    QUOTA_MESSAGES_GRATUIT_JOUR: int = 40
    BUDGET_MENSUEL_USD: float = 200.0

    @property
    def db_url(self) -> str:
        raw = self.DATABASE_URL or "sqlite:///./onemoov.db"
        # Render / Heroku fournissent 'postgres://' ou 'postgresql://' ; on force le
        # driver psycopg (v3), seul installé, sinon SQLAlchemy cherche psycopg2.
        if raw.startswith("postgres://"):
            raw = "postgresql+psycopg://" + raw[len("postgres://"):]
        elif raw.startswith("postgresql://"):
            raw = "postgresql+psycopg://" + raw[len("postgresql://"):]
        return raw

    @property
    def groq_models(self) -> list[str]:
        return [m.strip() for m in self.GROQ_MODELS.split(",") if m.strip()]

    @property
    def secours_models(self) -> list[str]:
        return [m.strip() for m in self.SECOURS_MODELS.split(",") if m.strip()]

    @property
    def prix_fcfa(self) -> int:
        return round(self.PRIX_PARCOURS_EUR * self.TAUX_EUR_FCFA)


@lru_cache
def get_settings() -> Settings:
    return Settings()
