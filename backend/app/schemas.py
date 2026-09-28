"""
schemas.py — Contrats Pydantic (entrée/sortie de l'API).
"""
from pydantic import BaseModel, EmailStr, Field


# ── Auth ──────────────────────────────────────────────────────────
class RegisterIn(BaseModel):
    email: EmailStr
    password: str          # robustesse validée côté route (message en français)
    prenom: str = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class EmailIn(BaseModel):
    email: EmailStr


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    prenom: str = ""
    user_id: int


# ── Conversation / orientation ────────────────────────────────────
class Message(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    piste_id: int | None = None
    messages: list[Message]
    max_tokens: int | None = 800


class FormationsIn(BaseModel):
    piste_id: int | None = None
    messages: list[Message] = []
    profil: dict | None = None   # optionnel : sinon extrait de la conversation


# ── Parcours / roadmap ────────────────────────────────────────────
class VoieIn(BaseModel):
    piste_id: int
    voie: str  # "public" | "prive"


class RncpVerifyIn(BaseModel):
    piste_id: int | None = None
    intitule: str
    etablissement: str = ""
    code_rncp: str = ""


# ── Paiement ──────────────────────────────────────────────────────
class PaiementCreateIn(BaseModel):
    piste_id: int


# ── Chatbot popup ─────────────────────────────────────────────────
class ChatbotIn(BaseModel):
    piste_id: int
    etape: str = ""
    messages: list[Message]


# ── Aides IA (entretien / contestation) ───────────────────────────
class EntretienIn(BaseModel):
    piste_id: int
    messages: list[Message] = []


class ContestationIn(BaseModel):
    piste_id: int
    type_refus: str = "admission"      # "admission" | "visa"
    formation: str = ""
    etablissement: str = ""
    motif: str = ""                     # motif du refus si connu
    arguments: str = ""                 # éléments que l'étudiant veut faire valoir
