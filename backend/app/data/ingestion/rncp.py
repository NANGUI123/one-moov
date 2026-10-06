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
import re
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


def _remplacant(row: dict) -> str:
    """Le code de la fiche qui remplace celle-ci, si l'export le donne.

    France Compétences nomme cette colonne différemment selon les exports.
    Plusieurs codes peuvent être listés ; on garde le premier, qui suffit à
    envoyer l'étudiant au bon endroit.
    """
    brut = _pick(row, "Nouvelle_Certification", "Nouvelle_certification",
                 "Nouvelles_Certifications", "nouvelle_certification",
                 "Remplace_Par", "remplace_par")
    codes = re.findall(r"(?:RNCP|RS)\s*\d+", brut, flags=re.I)
    return codes[0].upper().replace(" ", "") if codes else ""


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
            # Une colonne d'état absente valait « actif » : un faux positif
            # silencieux, et le pire sens pour un défaut de données. Une
            # fiche dont on ignore l'état n'est pas une fiche active.
            "actif": _is_actif(etat),
            "etat": etat,
            "remplace_par": _remplacant(row),
            "niveau": _pick(row, "Nomenclature_Europe_Niveau", "Niveau", "niveau"),
            "certificateurs": _pick(row, "Nom_Legal_Certificateur", "Nom_Certificateur",
                                    "Certificateurs", "certificateur"),
            "date_fin": _pick(row, "Date_Fin_Enregistrement", "date_fin"),
        })
    return rows


def fusionner(fiches: list[dict]) -> list[dict]:
    """Une seule ligne par code.

    L'archive peut contenir plusieurs CSV qui répètent le même code (fiche,
    certificateurs, remplacements…). Sans fusion, une ligne annexe sans état
    ni intitulé pouvait être celle que la vérification retrouvait, et passer
    pour une fiche inactive. Ici, l'état ne vient que des lignes qui en
    déclarent un, et les certificateurs de toutes les lignes sont réunis.
    """
    groupes: dict[str, list[dict]] = {}
    out: list[dict] = []
    for f in fiches:
        if f["code_rncp"]:
            groupes.setdefault(f["code_rncp"], []).append(f)
        else:
            out.append(f)
    for code, lignes in groupes.items():
        def premier(champ: str) -> str:
            return next((l[champ] for l in lignes if l[champ]), "")
        certificateurs = dict.fromkeys(l["certificateurs"] for l in lignes if l["certificateurs"])
        out.append({
            "code_rncp": code,
            "intitule": premier("intitule"),
            "etat": premier("etat"),
            "actif": any(l["actif"] for l in lignes if l["etat"]),
            "remplace_par": premier("remplace_par"),
            "niveau": premier("niveau"),
            "certificateurs": " ; ".join(certificateurs),
            "date_fin": premier("date_fin"),
        })
    return out


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
                    lignes = parse_csv_bytes(z.read(name))
                    logger.info(f"Export RNCP : {name} → {len(lignes)} lignes")
                    fiches += lignes
    else:
        fiches = parse_csv_bytes(resp.content)
    fiches = fusionner(fiches)

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
