"""
routers/rncp.py — Vérification du titre RNCP (parcours privé).

Ordre de consultation : la base d'abord, le modèle ensuite.

Pourquoi cet ordre, et pourquoi il a changé
-------------------------------------------
La version précédente interrogeait d'abord un modèle connecté au web, et ne
se repliait sur l'export officiel qu'en cas d'échec. C'était l'inverse du
principe que le produit annonce : le modèle propose, la donnée fait autorité.
Sur cette fonction, le modèle décidait.

Trois niveaux, dans cet ordre :

  1. l'export officiel France Compétences synchronisé localement. Réponse
     déterministe, vérifiable, avec sa date de synchronisation ;
  2. un modèle connecté au web, uniquement quand la base ne connaît pas la
     formation, et toujours étiqueté comme non confirmé ;
  3. le lien vers la recherche officielle, pour que l'étudiant tranche
     lui-même.

Le niveau 2 reste une réponse de modèle. Il est conservé parce qu'un
étudiant devant une école privée inconnue de notre base préfère une piste
étiquetée à un écran vide, et parce que notre base ne couvre pas encore tout
le répertoire. L'élargir est financé dans le plan ; d'ici là, l'étiquette
est ce qui sépare une indication d'une affirmation.
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user_optional
from app.models import User, Piste
from app.schemas import RncpVerifyIn
from app.services import rncp_client, rncp_web

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rncp", tags=["rncp"])

# Statuts pour lesquels la base a tranché. Tout le reste signifie « je ne
# sais pas », et c'est le seul cas où le modèle a le droit d'intervenir.
STATUTS_FERMES = ("actif", "absent", "inactif", "expire")


@router.post("/verify")
def verify(body: RncpVerifyIn, db: Session = Depends(get_db),
           user: User | None = Depends(get_current_user_optional)):
    # 1. La base fait autorité.
    res = rncp_client.verifier(db, intitule=body.intitule, code_rncp=body.code_rncp,
                               etablissement=body.etablissement)

    # 2. Elle ne connaît pas cette formation : on tente le modèle, en le
    #    disant. Une erreur ici n'est pas une panne, c'est l'absence d'un
    #    complément — la réponse de la base reste valable.
    if res.get("statut") not in STATUTS_FERMES and rncp_web.disponible():
        try:
            complement = rncp_web.verifier(intitule=body.intitule,
                                           code_rncp=body.code_rncp,
                                           etablissement=body.etablissement)
        except Exception as e:
            logger.warning("Complément RNCP par modèle indisponible (%s) — "
                           "on s'en tient à la réponse de la base.", e)
        else:
            if complement:
                complement["statut_confiance"] = "non confirme"
                complement["origine"] = "modele_web"
                complement["avertissement"] = (
                    "Cette information vient d'un modèle connecté au web et "
                    "n'a pas été confirmée dans l'export officiel. "
                    "Vérifiez-la sur francecompetences.fr avant de vous "
                    "engager."
                )
                # Jamais de recommandation sur une réponse non confirmée :
                # déconseiller ou rassurer sur cette base engagerait une
                # décision que la donnée ne soutient pas.
                complement["deconseille"] = False
                res = complement
    else:
        res["statut_confiance"] = "confirme" if res.get("statut") in STATUTS_FERMES else "inconnu"
        res["origine"] = "base_officielle"

    if body.piste_id and user:
        p = db.get(Piste, body.piste_id)
        if p and p.user_id == user.id:
            p.formation_privee = {"intitule": body.intitule,
                                  "etablissement": body.etablissement,
                                  "code_rncp": body.code_rncp}
            p.rncp = res
            db.commit()
    return res
