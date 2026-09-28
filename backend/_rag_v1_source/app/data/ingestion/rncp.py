"""
data/ingestion/rncp.py — Synchronisation du référentiel RNCP.

On télécharge l'export officiel France Compétences publié sur data.gouv.fr
(export CSV des fiches RNCP, mis à jour quotidiennement), on le charge dans la
table `rncp_fiches`, puis la vérification se fait par lookup déterministe local
(rapide, hors-ligne, fiable). C'est le mode « sync de l'export officiel ».

Lancement : python -m app.scripts.sync_rncp
"""
import io
import csv
import zipfile
import logging
from datetime import date
import httpx
from sqlalchemy.orm import Session
from app.models import RncpFiche

logger = logging.getLogger(__name__)

DATASET = ("https://www.data.gouv.fr/api/1/datasets/"
           "repertoire-national-des-certifications-professionnelles-et-repertoire-specifique/")


def _latest_csv_zip_url() -> str | None:
    """Trouve l'URL du dernier export CSV des fiches sur data.gouv.fr."""
    r = httpx.get(DATASET, timeout=30)
    r.raise_for_status()
    resources = r.json().get("resources", [])
    candidates = [res for res in resources
                  if "export-fiches-csv" in (res.get("title", "").lower())
                  and (res.get("format", "").lower() in ("zip", "csv"))]
    if not candidates:
        candidates = [res for res in resources if res.get("url", "").endswith(".zip")
                      and "csv" in res.get("url", "").lower()]
    if not candidates:
        return None
    candidates.sort(key=lambda res: res.get("last_modified") or res.get("created_at") or "", reverse=True)
    return candidates[0].get("url")


def _pick(row: dict, *keys) -> str:
    """Récupère la 1ʳᵉ colonne existante (insensible à la casse/aux accents de header)."""
    low = {k.lower().strip(): v for k, v in row.items() if k}
    for key in keys:
        if key.lower() in low and low[key.lower()] not in (None, ""):
            return str(low[key.lower()]).strip()
    return ""


def _is_actif(val: str) -> bool:
    return val.strip().lower() in ("active", "actif", "oui", "true", "1", "publiée", "publiee")


def parse_csv_bytes(data: bytes) -> list[dict]:
    """Parse un CSV France Compétences (délimiteur ';', UTF-8 ou Latin-1)."""
    for enc in ("utf-8-sig", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return []
    delim = ";" if text[:2000].count(";") >= text[:2000].count(",") else ","
    rows = []
    for row in csv.DictReader(io.StringIO(text), delimiter=delim):
        code = _pick(row, "Numero_Fiche", "Numero_fiche", "numero_fiche", "code_rncp", "Code")
        intitule = _pick(row, "Intitule", "Intitulé", "libelle", "Libelle")
        if not code and not intitule:
            continue
        etat = _pick(row, "Actif", "Etat_Fiche", "Etat", "statut")
        rows.append({
            "code_rncp": code.upper().replace(" ", ""),
            "intitule": intitule,
            "actif": _is_actif(etat) if etat else True,
            "etat": etat,
            "niveau": _pick(row, "Nomenclature_Europe_Niveau", "Niveau", "niveau"),
            "certificateurs": _pick(row, "Nom_Legal_Certificateur", "Certificateurs", "certificateur"),
            "date_fin": _pick(row, "Date_Fin_Enregistrement", "date_fin"),
        })
    return rows


def sync(db: Session) -> int:
    """Télécharge l'export officiel et (re)charge la table rncp_fiches. Retourne le nb de fiches."""
    url = _latest_csv_zip_url()
    if not url:
        raise RuntimeError("Export CSV RNCP introuvable sur data.gouv.fr")
    logger.info(f"Téléchargement export RNCP : {url}")
    resp = httpx.get(url, timeout=120, follow_redirects=True)
    resp.raise_for_status()

    fiches: list[dict] = []
    if url.lower().endswith(".zip") or resp.headers.get("content-type", "").startswith("application/zip"):
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            for name in z.namelist():
                if name.lower().endswith(".csv"):
                    fiches += parse_csv_bytes(z.read(name))
    else:
        fiches = parse_csv_bytes(resp.content)

    if not fiches:
        raise RuntimeError("Aucune fiche RNCP parsée depuis l'export")

    today = str(date.today())
    db.query(RncpFiche).delete()                 # remplacement complet
    db.bulk_save_objects([RncpFiche(date_sync=today, **f) for f in fiches])
    db.commit()
    logger.info(f"RNCP synchronisé : {len(fiches)} fiches ({today})")
    return len(fiches)


def count(db: Session) -> int:
    return db.query(RncpFiche).count()
