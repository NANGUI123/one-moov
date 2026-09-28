"""Contrats de données.

La validation se fait à la frontière : ce qui entre est vérifié avant
d'atteindre la logique, ce qui sort respecte une forme connue du frontend.

Les énumérations à valeurs fermées sont volontaires. Un modèle de langage
n'est pas déterministe : sur un même récit il peut répondre « Maîtrise »
puis « Master ». Le contrat rejette tout ce qui sort de la liste, ce qui
empêche une valeur bancale d'entrer dans le système.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Énumérations
# --------------------------------------------------------------------------

class Niveau(str, Enum):
    licence = "licence"
    master = "master"
    doctorat = "doctorat"
    autre = "autre"


class Formation(str, Enum):
    initiale = "initiale"
    alternance = "alternance"
    continue_ = "continue"


class LangueEnseignement(str, Enum):
    francais = "francais"
    anglais = "anglais"


class Secteur(str, Enum):
    public = "public"
    prive = "prive"


class TypeEntretien(str, Enum):
    campus_france = "campus_france"
    ambassade = "ambassade"


class ModeConversation(str, Enum):
    guidee = "guidee"
    libre = "libre"


# --------------------------------------------------------------------------
# Profil
# --------------------------------------------------------------------------

class Profil(BaseModel):
    """Profil de l'étudiant.

    Il n'est jamais enregistré côté serveur. Il vit dans le navigateur et
    accompagne chaque requête. Aucun champ d'identité n'y figure : ni nom,
    ni courriel, ni numéro de document.
    """

    domaine: Optional[str] = None
    niveau: Optional[Niveau] = None
    formation: Optional[Formation] = None
    budget_mensuel: Optional[int] = Field(None, ge=0, le=10000)
    budget_scolarite_an: Optional[int] = Field(None, ge=0, le=100000)
    langue_enseignement: LangueEnseignement = LangueEnseignement.francais
    pays_origine: Optional[str] = None
    pays_destination: str = "France"
    projet_etudes: Optional[str] = Field(None, max_length=600)
    projet_pro: Optional[str] = Field(None, max_length=600)

    def est_complet(self) -> bool:
        return all([
            self.domaine, self.niveau, self.formation,
            self.budget_mensuel is not None, self.pays_origine,
            self.projet_etudes, self.projet_pro,
        ])


class MessageEchange(BaseModel):
    role: str = Field(..., pattern="^(etudiant|agent)$")
    texte: str = Field(..., max_length=2000)


# --------------------------------------------------------------------------
# Agent 1, orientation
# --------------------------------------------------------------------------

class RequeteOrientation(BaseModel):
    mode: ModeConversation = ModeConversation.guidee
    profil: Profil = Field(default_factory=Profil)
    historique: list[MessageEchange] = Field(default_factory=list, max_length=20)
    message: str = Field("", max_length=2000)


class ReponseOrientation(BaseModel):
    message: str
    profil: Profil
    suggestions: list[str] = Field(default_factory=list)
    complet: bool = False
    champ_attendu: Optional[str] = None


# --------------------------------------------------------------------------
# Feuille de route
# --------------------------------------------------------------------------

class RequeteRoadmap(BaseModel):
    profil: Profil
    secteurs: list[Secteur] = Field(default_factory=lambda: [Secteur.public])


class EtablissementPropose(BaseModel):
    id: str
    nom: str
    ville: str
    secteur: str
    frais_scolarite_an: int
    description: str
    site_web: Optional[str] = None
    verifie_le: str
    pourquoi: Optional[str] = None
    origine: str = "base"          # toujours la base, jamais le modèle


class VilleProposee(BaseModel):
    nom: str
    region: str
    cout_vie_mensuel: int
    loyer_moyen_studio: int
    pourquoi: Optional[str] = None
    origine: str = "base"


class EtapeRoadmap(BaseModel):
    ordre: int
    phase: str
    titre: str
    description: str
    actions: list[str] = Field(default_factory=list)
    faits: list[dict] = Field(default_factory=list)      # valeurs vérifiées
    sources: list[dict] = Field(default_factory=list)    # passages RAG cités
    liens: list[dict] = Field(default_factory=list)      # liens utiles associés à l'étape
    origine: str = "rag"


class Roadmap(BaseModel):
    resume: str
    analyse_budget: str
    villes: list[VilleProposee]
    etablissements: list[EtablissementPropose]
    etapes: list[EtapeRoadmap]
    faits_cles: list[dict] = Field(default_factory=list)
    genere_le: str
    version_connaissance: dict = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Agent 2, coach
# --------------------------------------------------------------------------

class RequeteCoach(BaseModel):
    profil: Profil = Field(default_factory=Profil)
    etape_courante: Optional[str] = None
    historique: list[MessageEchange] = Field(default_factory=list, max_length=20)
    message: str = Field("", max_length=2000)


class ReponseCoach(BaseModel):
    message: str
    prochaine_action: Optional[str] = None
    faits: list[dict] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Entretien
# --------------------------------------------------------------------------

class RequeteQuestion(BaseModel):
    type_entretien: TypeEntretien = TypeEntretien.campus_france
    profil: Profil = Field(default_factory=Profil)
    criteres_poses: list[str] = Field(default_factory=list)


class ReponseQuestion(BaseModel):
    question: str
    critere: str
    critere_libelle: str
    restants: int


class RequeteEvaluation(BaseModel):
    question: str = Field(..., max_length=1000)
    critere: str
    reponse: str = Field(..., max_length=4000)


class ReponseEvaluation(BaseModel):
    note: int = Field(..., ge=0, le=5)
    critere: str
    critere_libelle: str
    commentaire: str
    conseil: str
