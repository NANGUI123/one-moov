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
from datetime import date, datetime
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
            return _verdict(fiche, etablissement)
        return _res("absent", code_rncp=code_rncp, url_fiche=_url_fiche(code_rncp),
                    deconseille=True,
                    message=f"Le code {code_rncp} n'existe pas au RNCP — formation à écarter.")

    # 2) Par intitulé + établissement (certificateur)
    fiche, score = _chercher(db, intitule, etablissement)
    if fiche and score >= 3:
        return _verdict(fiche, etablissement)

    return _res("indetermine", url_fiche=_url_fiche(""), deconseille=False,
                message="Titre non retrouvé automatiquement par son intitulé. Saisissez le "
                        "code RNCP (ex. RNCP34567) pour une vérification fiable, ou vérifiez "
                        "directement sur France Compétences.")


def echue(date_fin: str, aujourdhui: date | None = None) -> bool:
    """La date de fin d'enregistrement est-elle dépassée ?

    L'export mélange les formats : « 31/08/2028 » le plus souvent, parfois
    « 2028-08-31 », parfois un horodatage. Une date illisible n'est pas une
    date dépassée : on renvoie False, et c'est l'état déclaré qui tranche.
    """
    s = (date_fin or "").strip()[:10]
    if not s:
        return False
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date() < (aujourdhui or date.today())
        except ValueError:
            continue
    return False


def couvre_etablissement(certificateurs: str, etablissement: str) -> bool | None:
    """L'établissement demandé figure-t-il parmi les certificateurs ?

    True, False, ou None quand la question n'a pas de sens : pas
    d'établissement demandé, ou une fiche nationale dont l'export ne donne
    que le nombre de certificateurs au lieu de leurs noms.
    """
    ne, nc = _norm(etablissement), _norm(certificateurs)
    if not ne or not nc:
        return None
    if re.search(r"\d+\s+certificateurs", nc):
        return None
    return ne in nc or nc in ne


def _chercher(db: Session, intitule: str, etablissement: str) -> tuple[RncpFiche | None, int]:
    """Recherche par intitulé, l'établissement ne servant qu'à départager.

    Le certificateur ne suffit plus à retenir une fiche : il valait trois
    points, soit le seuil, donc « Université de Nantes » plus n'importe quel
    intitulé tombait sur le premier master de cette université. Il faut
    désormais au moins deux mots de l'intitulé, et le bonus de certificateur
    ne s'applique qu'à une fiche déjà plausible.

    Le bonus « +1 si la fiche est active » a disparu : il poussait vers une
    fiche active au détriment de la bonne fiche expirée, c'est-à-dire qu'il
    masquait exactement ce que cette fonction doit faire voir.
    """
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
        mots_trouves = sum(1 for m in mots if m in rn)
        exact = bool(ni) and (ni in rn or rn in ni)
        if mots_trouves < 2 and not exact:
            continue                       # le certificateur seul ne décide pas
        score = mots_trouves + (5 if exact else 0)
        if ne and (ne in rc or (rc and rc in ne)):
            score += 3
        if score > best_score:
            best, best_score = r, score
    return best, best_score


def _verdict(fiche: RncpFiche, etablissement: str = "") -> dict:
    """Croise l'état déclaré, l'échéance et le remplacement.

    L'état déclaré ne suffit pas. France Compétences laisse des fiches
    marquées actives dont l'enregistrement est échu, le temps que le
    remplacement se traite. Une fiche échue est traitée comme expirée quoi
    qu'en dise la colonne d'état.
    """
    remplacant = (getattr(fiche, "remplace_par", "") or "").strip()
    est_echue = echue(fiche.date_fin)
    expire = (not fiche.actif) or est_echue or bool(remplacant)

    if expire:
        if est_echue and fiche.actif:
            msg = (f"Titre RNCP expiré : enregistrement échu le "
                   f"{fiche.date_fin}, bien que l'export le déclare encore "
                   f"actif. Formation déconseillée.")
        elif est_echue:
            msg = (f"Titre RNCP expiré le {fiche.date_fin} — formation "
                   f"déconseillée.")
        else:
            msg = "Titre RNCP trouvé mais non actif — formation déconseillée."
        if remplacant:
            msg += (f" Cette fiche est remplacée par {remplacant} : c'est "
                    f"celle-là qu'il faut vérifier.")
    else:
        msg = ("Titre RNCP actif et reconnu par l'État"
               + (f" (certificateur : {fiche.certificateurs})"
                  if fiche.certificateurs else "") + ".")

    # Une fiche nationale couvre des dizaines d'établissements. Dire qu'un
    # master est enregistré sous tel code est exact et ne prouve rien sur
    # l'école : on le dit plutôt que de laisser croire le contraire.
    reserve = ""
    couvre = couvre_etablissement(fiche.certificateurs or "", etablissement)
    if couvre is None and etablissement:
        reserve = (f"Fiche partagée par plusieurs établissements : le "
                   f"rattachement de « {etablissement} » n'est pas vérifié "
                   f"par cet export.")
    elif couvre is False:
        reserve = (f"« {etablissement} » ne figure pas parmi les "
                   f"certificateurs de cette fiche.")
    if reserve:
        msg += " " + reserve

    return _res("expire" if expire else "actif",
                code_rncp=fiche.code_rncp, intitule=fiche.intitule,
                certificateurs=[fiche.certificateurs] if fiche.certificateurs else [],
                niveau=fiche.niveau or "", date_echeance=fiche.date_fin or "",
                url_fiche=_url_fiche(remplacant or fiche.code_rncp),
                remplace_par=remplacant, reserve=reserve,
                deconseille=expire, message=msg, date_verif=fiche.date_sync)


def _res(statut, **kw) -> dict:
    base = {"statut": statut, "code_rncp": "", "intitule": "", "certificateurs": [],
            "niveau": "", "date_echeance": "", "url_fiche": "",
            "message": "", "deconseille": statut in ("absent", "inactif", "expire"),
            "date_verif": "", "source": "France Compétences (export officiel synchronisé)"}
    base.update(kw)
    return base
