"""
routers/rncp.py — Vérification RNCP (parcours privé).

Deux moteurs :
- si une clé LLM web est configurée (RNCP_LLM_API_KEY) → vérification par LLM
  connecté à internet (point 8) : renvoie nom du titre, numéro, niveau, date d'échéance ;
- sinon → repli sur l'export officiel France Compétences synchronisé localement.
Dans les deux cas : si le titre est expiré / inexistant, on déconseille la formation.
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


@router.post("/verify")
def verify(body: RncpVerifyIn, db: Session = Depends(get_db),
           user: User | None = Depends(get_current_user_optional)):
    res = None
    if rncp_web.disponible():
        try:
            res = rncp_web.verifier(intitule=body.intitule, code_rncp=body.code_rncp,
                                    etablissement=body.etablissement)
        except Exception as e:
            logger.warning(f"Vérif RNCP web échouée ({e}) — repli sur l'export officiel local")
    if res is None:
        res = rncp_client.verifier(db, intitule=body.intitule, code_rncp=body.code_rncp,
                                   etablissement=body.etablissement)

    if body.piste_id and user:
        p = db.get(Piste, body.piste_id)
        if p and p.user_id == user.id:
            p.formation_privee = {"intitule": body.intitule, "etablissement": body.etablissement,
                                  "code_rncp": body.code_rncp}
            p.rncp = res
            db.commit()
    return res
