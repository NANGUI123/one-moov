"""La cascade de repli : fournisseur nominal, secours ailleurs, mode guidé.

Ces tests n'appellent aucun service externe. Ils remplacent les clients par
des doubles qui réussissent ou échouent à la demande, ce qui est le seul
moyen de vérifier un comportement de panne sans attendre une vraie panne.
"""

import pytest

from app.services import llm as mod


class _Reponse:
    def __init__(self, texte):
        self.choices = [type("C", (), {"message": type("M", (), {"content": texte})})]
        self.usage = None


class _Client:
    """Double de client : répond, ou lève, selon ce qu'on lui demande."""

    def __init__(self, texte=None, erreur=None):
        self.texte, self.erreur = texte, erreur
        self.appels = []
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, model, **kwargs):
        self.appels.append(model)
        if self.erreur:
            raise RuntimeError(self.erreur)
        return _Reponse(self.texte)


def _cascade(principal=None, secours=None, modeles=("m1", "m2"),
             modeles_secours=("s1",)):
    c = mod.CascadeLLM.__new__(mod.CascadeLLM)
    c._principal = principal
    c._secours = secours
    c.models = list(modeles)
    c.models_secours = list(modeles_secours) if secours else []
    c.model_leger = modeles[0]
    return c


def test_le_premier_modele_qui_repond_gagne():
    p = _Client(texte="ok")
    c = _cascade(principal=p)
    assert c.chat([{"role": "user", "content": "salut"}]) == "ok"
    assert p.appels == ["m1"], "on ne doit pas essayer le second si le premier répond"


def test_un_modele_en_panne_passe_au_suivant_chez_le_meme_hebergeur():
    """Le cas du 16 août : un modèle quitte le catalogue, l'autre répond."""
    class Mixte(_Client):
        def create(self, model, **kwargs):
            self.appels.append(model)
            if model == "m1":
                raise RuntimeError("model_decommissioned")
            return _Reponse("réponse du second")

    p = Mixte()
    c = _cascade(principal=p)
    assert c.chat([{"role": "user", "content": "x"}]) == "réponse du second"
    assert p.appels == ["m1", "m2"]


def test_une_panne_d_hebergeur_bascule_sur_le_secours():
    """Tous les modèles du nominal tombent ensemble : c'est à ça que sert
    un second hébergeur, et c'est ce qu'une simple cascade ne couvrait pas."""
    p = _Client(erreur="503 service unavailable")
    s = _Client(texte="servi par le secours")
    c = _cascade(principal=p, secours=s)
    assert c.chat([{"role": "user", "content": "x"}]) == "servi par le secours"
    assert p.appels == ["m1", "m2"], "les deux modèles nominaux ont été tentés"
    assert s.appels == ["s1"]


def test_sans_secours_une_panne_d_hebergeur_mene_au_mode_guide():
    c = _cascade(principal=_Client(erreur="503"))
    with pytest.raises(mod.LLMUnavailable):
        c.chat([{"role": "user", "content": "x"}])


def test_sans_aucune_cle_le_mode_guide_est_immediat():
    c = _cascade()
    assert c.available is False
    with pytest.raises(mod.LLMUnavailable):
        c.chat([{"role": "user", "content": "x"}])


def test_le_secours_seul_suffit_a_rendre_le_service_disponible():
    c = _cascade(secours=_Client(texte="ok"))
    assert c.available is True
    assert c.chat([{"role": "user", "content": "x"}]) == "ok"


def test_le_mode_leger_ne_tente_que_le_petit_modele_du_nominal():
    p = _Client(texte="ok")
    c = _cascade(principal=p)
    c.chat([{"role": "user", "content": "x"}], leger=True)
    assert p.appels == ["m1"]


def test_l_etat_annonce_le_nombre_reel_de_niveaux_avec_ia():
    """L'écran de santé doit dire la vérité sur la résilience disponible."""
    assert _cascade(principal=_Client()).etat()["niveaux_avec_ia"] == 1
    assert _cascade(principal=_Client(), secours=_Client()).etat()["niveaux_avec_ia"] == 2
    assert _cascade().etat()["niveaux_avec_ia"] == 0
