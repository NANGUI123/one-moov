"""
services/rncp_web.py — Vérification RNCP par un LLM connecté à internet (point 8).

À partir de l'établissement + l'intitulé (et éventuellement le code), on interroge
un LLM avec accès web (par défaut Perplexity « sonar », configurable via
RNCP_LLM_BASE_URL / RNCP_LLM_MODEL / RNCP_LLM_API_KEY — compatible OpenAI). On récupère,
depuis France Compétences : le nom du titre, le numéro RNCP, le niveau et la date
d'échéance d'enregistrement. Règle : si le titre est expiré ou inexistant → on déconseille.

⚠️ La réponse provient d'un LLM : on l'affiche avec un rappel de vérifier sur
francecompetences.fr. Sans clé configurée, l'appelant bascule sur l'export officiel local.
"""
import json
import logging
import re
from openai import OpenAI
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

SYSTEM = (
    "Tu es un vérificateur de titres RNCP (Répertoire National des Certifications "
    "Professionnelles, France Compétences). Tu utilises tes accès web pour trouver la "
    "fiche officielle correspondant à l'établissement et à l'intitulé fournis, sur "
    "francecompetences.fr. Tu ne dois RIEN inventer : si tu n'es pas sûr, mets found=false. "
    "Réponds UNIQUEMENT par un objet JSON valide, sans texte autour."
)

TEMPLATE = (
    "Recherche la fiche RNCP officielle correspondant à :\n"
    "- Établissement / certificateur : {etablissement}\n"
    "- Intitulé de la formation : {intitule}\n"
    "- Code RNCP éventuel : {code}\n\n"
    "Renvoie STRICTEMENT ce JSON :\n"
    '{{"found": true/false, "code_rncp": "RNCPxxxxx", "intitule_officiel": "...", '
    '"certificateur": "...", "niveau": "Niveau x", "date_echeance": "AAAA-MM-JJ ou \'\'", '
    '"actif": true/false, "expire": true/false, "commentaire": "1 phrase"}}\n'
    "Si tu ne trouves pas de fiche fiable, mets found=false."
)


def _client() -> OpenAI:
    return OpenAI(api_key=settings.RNCP_LLM_API_KEY, base_url=settings.RNCP_LLM_BASE_URL)


def disponible() -> bool:
    return bool(settings.RNCP_LLM_API_KEY)


def verifier(intitule: str = "", code_rncp: str = "", etablissement: str = "") -> dict:
    """Interroge le LLM web. Lève une exception en cas d'échec (→ repli local)."""
    prompt = TEMPLATE.format(etablissement=etablissement or "(non précisé)",
                             intitule=intitule or "(non précisé)",
                             code=code_rncp or "(non précisé)")
    resp = _client().chat.completions.create(
        model=settings.RNCP_LLM_MODEL,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": prompt}],
        temperature=0.1, max_tokens=500,
    )
    raw = resp.choices[0].message.content or ""
    data = json.loads(_extract_json(raw))
    return _map(data)


def _extract_json(raw: str) -> str:
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()
    i, j = s.find("{"), s.rfind("}")
    return s[i:j + 1] if i >= 0 and j > i else s


def _map(d: dict) -> dict:
    found = bool(d.get("found"))
    actif = bool(d.get("actif"))
    expire = bool(d.get("expire"))
    if not found:
        statut = "absent"
    elif expire or not actif:
        statut = "expire"
    else:
        statut = "actif"
    deconseille = statut != "actif"

    if statut == "actif":
        msg = "Titre RNCP actif et enregistré."
    elif statut == "expire":
        msg = "Titre RNCP trouvé mais expiré ou non actif — formation déconseillée."
    else:
        msg = "Aucune fiche RNCP fiable trouvée pour cette formation — à écarter par prudence."
    if d.get("commentaire"):
        msg += f" {d['commentaire']}"

    code = (d.get("code_rncp", "") or "").upper().replace(" ", "")
    url_fiche = (f"https://www.francecompetences.fr/recherche_certificationprofessionnelle/?text={code}"
                 if code else "https://www.francecompetences.fr/recherche_certificationprofessionnelle/")
    return {
        "statut": statut,
        "code_rncp": code,
        "intitule": d.get("intitule_officiel", "") or "",
        "certificateurs": [d["certificateur"]] if d.get("certificateur") else [],
        "niveau": d.get("niveau", "") or "",
        "date_echeance": d.get("date_echeance", "") or "",
        "url_fiche": url_fiche,
        "deconseille": deconseille,
        "message": msg,
        "date_verif": "",
        "source": f"Vérifié via LLM web ({settings.RNCP_LLM_MODEL}) — à confirmer sur francecompetences.fr",
    }
