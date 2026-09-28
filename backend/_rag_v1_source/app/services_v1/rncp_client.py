"""
services/rncp_client.py — Vérification RNCP par lookup déterministe local.

La table `rncp_fiches` est alimentée par le sync de l'export officiel
France Compétences (data/ingestion/rncp.py). On cherche par :
  1. code RNCP (le plus fiable),
  2. sinon intitulé + établissement (certificateur),
et on renvoie : actif / inactif / absent / indéterminé.

Règle honnête : on ne « déconseille » que sur un signal clair (code inexistant,
ou titre trouvé mais inactif). Un simple intitulé non retrouvé n'est PAS un rejet :
on invite à saisir le code RNCP.
"""
import re
import unicodedata
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models import RncpFiche


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def verifier(db: Session, intitule: str = "", code_rncp: str = "", etablissement: str = "") -> dict:
    if db.query(RncpFiche).count() == 0:
        return _res("indetermine", deconseille=False,
                    message="Base RNCP non synchronisée. Lancez : python -m app.scripts.sync_rncp")

    # 1) Par code RNCP — le plus fiable
    if code_rncp:
        code = code_rncp.upper().replace(" ", "")
        digits = re.sub(r"\D", "", code)
        cands = {code, f"RNCP{digits}", f"RS{digits}", digits}
        fiche = db.query(RncpFiche).filter(RncpFiche.code_rncp.in_(list(cands))).first()
        if fiche:
            return _verdict(fiche)
        return _res("absent", code_rncp=code_rncp, deconseille=True,
                    message=f"Le code {code_rncp} n'existe pas au RNCP — formation à écarter.")

    # 2) Par intitulé + établissement (certificateur)
    fiche, score = _chercher(db, intitule, etablissement)
    if fiche and score >= 3:
        return _verdict(fiche)

    return _res("indetermine", deconseille=False,
                message="Titre non retrouvé automatiquement par son intitulé. Saisis le "
                        "code RNCP (ex. RNCP34567) pour une vérification fiable, ou vérifie "
                        "sur francecompetences.fr.")


def _chercher(db: Session, intitule: str, etablissement: str) -> tuple[RncpFiche | None, int]:
    ni, ne = _norm(intitule), _norm(etablissement)
    mots = [m for m in ni.split() if len(m) > 3]
    clauses = [RncpFiche.intitule.ilike(f"%{m}%") for m in mots[:3]]
    if ne:
        clauses.append(RncpFiche.certificateurs.ilike(f"%{etablissement.strip()}%"))
    if not clauses:
        return None, 0
    rows = db.query(RncpFiche).filter(or_(*clauses)).limit(500).all()
    best, best_score = None, 0
    for r in rows:
        rn, rc = _norm(r.intitule), _norm(r.certificateurs)
        score = sum(1 for m in mots if m in rn)
        if ne and (ne in rc or (rc and rc in ne)):
            score += 3
        if ni and (ni in rn or rn in ni):
            score += 5
        if r.actif:
            score += 1
        if score > best_score:
            best, best_score = r, score
    return best, best_score


def _verdict(fiche: RncpFiche) -> dict:
    if fiche.actif:
        msg = ("Titre RNCP actif et reconnu par l'État"
               + (f" (certificateur : {fiche.certificateurs})" if fiche.certificateurs else "") + ".")
    else:
        msg = "Titre RNCP trouvé mais NON actif — formation déconseillée."
    return _res("actif" if fiche.actif else "inactif",
                code_rncp=fiche.code_rncp, intitule=fiche.intitule,
                certificateurs=[fiche.certificateurs] if fiche.certificateurs else [],
                niveau=fiche.niveau or "", date_echeance=fiche.date_fin or "",
                deconseille=not fiche.actif, message=msg, date_verif=fiche.date_sync)


def _res(statut, **kw) -> dict:
    base = {"statut": statut, "code_rncp": "", "intitule": "", "certificateurs": [],
            "niveau": "", "date_echeance": "",
            "message": "", "deconseille": statut in ("absent", "inactif", "expire"),
            "date_verif": "", "source": "France Compétences (export officiel synchronisé)"}
    base.update(kw)
    return base
