"""Quotas et plafond de dépense, comptés en base.

Le point de ces tests : la limite doit être juste quel que soit le nombre
d'instances. Compter en base est ce qui le garantit, et ces tests vérifient
qu'on compte bien ce qu'on croit compter.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import TokenUsage
from app.services import quotas


def _appel(db, user_id: int, quand: datetime | None = None, cout: float = 0.001):
    """Enregistre un appel au modèle, comme le ferait token_meter."""
    ligne = TokenUsage(user_id=user_id, endpoint="test", model="m",
                       prompt_tokens=10, completion_tokens=10, total_tokens=20,
                       cost_usd=cout)
    if quand is not None:
        ligne.created_at = quand
    db.add(ligne)
    db.commit()
    return ligne


@pytest.fixture()
def utilisateur(db):
    """Un identifiant propre à chaque test, pour que les comptes ne se
    mélangent pas d'un test à l'autre dans la base de session."""
    base = db.query(TokenUsage).count()
    return 9000 + base


def test_sans_appel_le_quota_est_entier(db, utilisateur):
    etat = quotas.etat(db, utilisateur)
    assert etat["utilises"] == 0
    assert etat["restants"] == quotas.limite_quotidienne()
    assert etat["atteint"] is False


def test_les_appels_du_jour_sont_comptes(db, utilisateur):
    for _ in range(3):
        _appel(db, utilisateur)
    assert quotas.appels_du_jour(db, utilisateur) == 3


def test_les_appels_d_hier_ne_comptent_pas(db, utilisateur):
    """Le quota repart à minuit, sinon il n'est pas journalier."""
    hier = datetime.now(timezone.utc) - timedelta(days=1)
    for _ in range(5):
        _appel(db, utilisateur, quand=hier)
    assert quotas.appels_du_jour(db, utilisateur) == 0


def test_les_appels_d_un_autre_utilisateur_ne_comptent_pas(db, utilisateur):
    _appel(db, utilisateur + 1)
    _appel(db, utilisateur + 1)
    assert quotas.appels_du_jour(db, utilisateur) == 0


def test_la_limite_declenche_la_bascule(db, utilisateur):
    for _ in range(quotas.limite_quotidienne()):
        _appel(db, utilisateur)
    assert quotas.depasse(db, utilisateur) is True
    raison = quotas.doit_basculer_en_guide(db, utilisateur)
    assert raison and "demain" in raison


def test_un_visiteur_sans_compte_n_est_pas_bloque(db):
    """Rien ne rattache ses appels : le quota ne s'applique pas, et c'est
    une limite assumée plutôt qu'un oubli."""
    assert quotas.depasse(db, None) is False
    assert quotas.doit_basculer_en_guide(db, None) is None


def test_un_plafond_de_depense_a_zero_ne_bloque_rien(db, monkeypatch):
    """Sinon le garde-fou serait une panne : la valeur par défaut couperait
    tout avant le premier appel."""
    monkeypatch.setattr(quotas.settings, "BUDGET_MENSUEL_USD", 0)
    _appel(db, 1, cout=10.0)
    assert quotas.budget_mensuel_depasse(db) is False


def test_un_plafond_atteint_bascule_tout_le_monde(db, utilisateur, monkeypatch):
    monkeypatch.setattr(quotas.settings, "BUDGET_MENSUEL_USD", 0.01)
    _appel(db, utilisateur, cout=1.0)
    assert quotas.budget_mensuel_depasse(db) is True
    raison = quotas.doit_basculer_en_guide(db, utilisateur)
    assert raison and "mode guidé" in raison


def test_une_depense_de_plus_de_trente_jours_ne_compte_plus(db, monkeypatch):
    """Le plafond glisse sur 30 jours : une dépense ancienne ne doit pas
    bloquer indéfiniment le service.

    La table est vidée d'abord : le plafond est global, donc ce test est le
    seul du fichier qui ne peut pas s'isoler par l'identifiant d'un
    utilisateur.
    """
    db.query(TokenUsage).delete()
    db.commit()
    monkeypatch.setattr(quotas.settings, "BUDGET_MENSUEL_USD", 0.5)
    vieux = datetime.now(timezone.utc) - timedelta(days=40)
    _appel(db, 1, quand=vieux, cout=100.0)
    assert quotas.budget_mensuel_depasse(db) is False
