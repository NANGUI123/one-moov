"""
services/rncp_client.py — Vérification RNCP par lookup déterministe local.

La table `rncp_fiches` est alimentée par le sync de l'export officiel
France Compétences (data/ingestion/rncp.py, déclenché en arrière-plan
au démarrage). On cherche par :
  1. code RNCP (le plus fiable),
  2. sinon intitulé + établissement (certificateur),
et on renvoie : actif / inactif / absent / indéterminé.

Règle honnête : on ne « déconseille » que sur un signal clair (code inexistant,
ou titre trouvé mais inactif). Un simple intitulé non retrouvé n'est PAS un rejet :
on invite à saisir le code RNCP.

Quand la base n'est pas encore prête (premier démarrage, sync en cours), on ne
renvoie plus le message technique « lancez python -m … ». On construit un lien
direct vers la fiche France Compétences si le code est fourni, sinon on
propose de consulter directement francecompetences.fr — jamais de dead-end
côté utilisateur.
"""
import re
import unicodedata
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models import RncpFiche


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _url_fiche(code_rncp: str) -> str:
    """Lien direct vers la fiche officielle France Compétences.

    Pattern d'URL vérifié auprès de l'utilisateur :
        https://www.francecompetences.fr/recherche/rncp/40531/
    C'est le numéro SEUL (chiffres) qui va dans l'URL — jamais le préfixe
    RNCP ou RS. On gère les deux répertoires (RNCP vs RS = Répertoire
    Spécifique) : /recherche/rncp/<n>/ pour RNCP, /recherche/rs/<n>/ pour RS.
    Sans code, on renvoie vers le moteur de recherche.
    """
    if not code_rncp:
        return "https://www.francecompetences.fr/recherche_certificationprofessionnelle/"
    code = code_rncp.upper().replace(" ", "")
    numero = re.sub(r"\D", "", code)
    if not numero:
        return "https://www.francecompetences.fr/recherche_certificationprofessionnelle/"
    repertoire = "rs" if code.startswith("RS") else "rncp"
    return f"https://www.francecompetences.fr/recherche/{repertoire}/{numero}/"


def verifier(db: Session, intitule: str = "", code_rncp: str = "", etablissement: str = "") -> dict:
    if db.query(RncpFiche).count() == 0:
        # Base pas encore prête : au lieu du message technique, on renvoie
        # le lien direct vers la fiche officielle (si code connu) ou vers
        # la recherche France Compétences (sinon). L'étudiant vérifie
        # lui-même en un clic pendant que le sync tourne en fond.
        if code_rncp:
            code = code_rncp.upper().replace(" ", "")
            return _res("indetermine", code_rncp=code, url_fiche=_url_fiche(code),
                        deconseille=False,
                        message=f"Vérification directe : ouvrez la fiche officielle "
                                f"{code} sur France Compétences.")
        return _res("indetermine", url_fiche=_url_fiche(""), deconseille=False,
                    message="Recherchez ce titre directement sur France Compétences "
                            "(lien officiel), en attendant que notre base soit prête.")

    # 1) Par code RNCP — le plus fiable
    if code_rncp:
        code = code_rncp.upper().replace(" ", "")
        digits = re.sub(r"\D", "", code)
        cands = {code, f"RNCP{digits}", f"RS{digits}", digits}
        fiche = db.query(RncpFiche).filter(RncpFiche.code_rncp.in_(list(cands))).first()
        if fiche:
            return _verdict(fiche)
        return _res("absent", code_rncp=code_rncp, url_fiche=_url_fiche(code_rncp),
                    deconseille=True,
                    message=f"Le code {code_rncp} n'existe pas au RNCP — formation à écarter.")

    # 2) Par intitulé + établissement (certificateur)
    fiche, score = _chercher(db, intitule, etablissement)
    if fiche and score >= 3:
        return _verdict(fiche)

    return _res("indetermine", url_fiche=_url_fiche(""), deconseille=False,
                message="Titre non retrouvé automatiquement par son intitulé. Saisissez le "
                        "code RNCP (ex. RNCP34567) pour une vérification fiable, ou vérifiez "
                        "directement sur France Compétences.")


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
                url_fiche=_url_fiche(fiche.code_rncp),
                deconseille=not fiche.actif, message=msg, date_verif=fiche.date_sync)


def _res(statut, **kw) -> dict:
    base = {"statut": statut, "code_rncp": "", "intitule": "", "certificateurs": [],
            "niveau": "", "date_echeance": "", "url_fiche": "",
            "message": "", "deconseille": statut in ("absent", "inactif", "expire"),
            "date_verif": "", "source": "France Compétences (export officiel synchronisé)"}
    base.update(kw)
    return base
