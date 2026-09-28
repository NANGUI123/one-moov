"""
models.py — Schéma de données (SQLAlchemy 2.0).

Principe de fiabilité : les FAITS (formations, RNCP) vivent en base, pas dans le LLM.
"""
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    prenom: Mapped[str] = mapped_column(String(120), default="")
    # Le pays de résidence adapte la procédure Campus France et la liste des
    # opérateurs mobile money proposés. Choisi à l'inscription, non modifiable
    # depuis l'app (pour éviter qu'un étudiant change de pays et invalide sa
    # feuille de route en cours). "" = ancien compte, à demander à la connexion.
    pays_residence: Mapped[str] = mapped_column(
        String(80), default="", server_default="",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    pistes: Mapped[list["Piste"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Piste(Base):
    __tablename__ = "pistes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    pays: Mapped[str] = mapped_column(String(80), default="Cameroun")
    voie: Mapped[str] = mapped_column(String(20), default="")          # "public" | "prive" | ""
    profil: Mapped[dict] = mapped_column(JSON, default=dict)            # projet académique + pro
    formations: Mapped[list] = mapped_column(JSON, default=list)        # les 10 formations proposées
    formation_privee: Mapped[dict] = mapped_column(JSON, default=dict)  # école/formation saisie (privé)
    rncp: Mapped[dict] = mapped_column(JSON, default=dict)              # résultat de vérification RNCP
    roadmap: Mapped[dict] = mapped_column(JSON, default=dict)          # arbre d'étapes + état
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="pistes")


class EmailVerification(Base):
    """Présence d'une ligne = e-mail vérifié (évite d'altérer la table users)."""
    __tablename__ = "email_verifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuthToken(Base):
    """Jetons à usage unique : vérification d'e-mail et réinitialisation de mot de passe."""
    __tablename__ = "auth_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="verify")   # "verify" | "reset"
    token: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Formation(Base):
    """Référentiel de formations (source de vérité). Alimenté par l'ingestion open data."""
    __tablename__ = "formations"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(60), default="")         # onisep / monmaster / parcoursup / seed
    code_rncp: Mapped[str] = mapped_column(String(20), default="", index=True)
    intitule: Mapped[str] = mapped_column(String(400), index=True)
    etablissement: Mapped[str] = mapped_column(String(400), default="")
    ville: Mapped[str] = mapped_column(String(160), default="", index=True)
    domaine: Mapped[str] = mapped_column(String(160), default="", index=True)
    niveau: Mapped[str] = mapped_column(String(80), default="")         # licence / master / bts / but ...
    voie: Mapped[str] = mapped_column(String(20), default="public")     # public / prive
    cout_annuel: Mapped[int] = mapped_column(Integer, default=0)        # EUR / an (0 = inconnu)
    langue: Mapped[str] = mapped_column(String(40), default="français")
    url: Mapped[str] = mapped_column(String(600), default="")
    provenance: Mapped[str] = mapped_column(String(200), default="")    # traçabilité de la fiche
    date_verif: Mapped[str] = mapped_column(String(40), default="")

    __table_args__ = ()


class RncpFiche(Base):
    """Référentiel RNCP synchronisé depuis l'export officiel France Compétences."""
    __tablename__ = "rncp_fiches"
    id: Mapped[int] = mapped_column(primary_key=True)
    code_rncp: Mapped[str] = mapped_column(String(20), index=True)
    intitule: Mapped[str] = mapped_column(String(600), index=True)
    actif: Mapped[bool] = mapped_column(Boolean, default=False)
    etat: Mapped[str] = mapped_column(String(40), default="")
    niveau: Mapped[str] = mapped_column(String(40), default="")
    certificateurs: Mapped[str] = mapped_column(Text, default="")
    date_fin: Mapped[str] = mapped_column(String(40), default="")
    date_sync: Mapped[str] = mapped_column(String(40), default="")


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    piste_id: Mapped[int] = mapped_column(ForeignKey("pistes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    transaction_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    amount_eur: Mapped[float] = mapped_column(Float, default=0.0)
    amount_fcfa: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str] = mapped_column(String(40), default="cinetpay")
    status: Mapped[str] = mapped_column(String(30), default="pending")  # pending / paid / failed
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TokenUsage(Base):
    """Un enregistrement par appel LLM — cœur du pilotage des coûts (point 6)."""
    __tablename__ = "token_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    piste_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    endpoint: Mapped[str] = mapped_column(String(60), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
