"""Les alias de domaine ne doivent pas détourner un champ vers un autre.

L'alias « ia » comparé par sous-chaîne envoyait « social », « médias » ou
« commercial » vers l'informatique.
"""

import pytest

from app.data.ingestion.onisep import charger_formations
from app.models import Formation
from app.services.orientation_engine import top_formations


@pytest.fixture(autouse=True)
def _catalogue(db):
    if db.query(Formation).count() == 0:
        charger_formations(db, force=True)


@pytest.mark.parametrize("demande, attendu", [
    ("Communication Médias", "Communication Médias"),
    ("Social Éducation", "Social Éducation"),
    ("Sciences sociales", "Social Éducation"),
    ("Commercial", "Commerce Gestion"),
    ("Développement durable", "Environnement Écologie"),
    ("Informatique/IA", "Informatique"),
])
def test_l_alias_mene_au_bon_domaine(db, demande, attendu):
    pistes = top_formations(db, {"domaine": demande, "niveau": "licence"}, k=3)
    assert [p["domaine"] for p in pistes] == [attendu] * 3
