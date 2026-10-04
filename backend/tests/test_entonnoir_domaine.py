"""L'entonnoir par domaine : la procédure ne dépend pas que du niveau.

Deux champs échappent à la règle « la DAP, c'est la première année ». La
santé et l'architecture relèvent de la Demande d'Admission Préalable quel que
soit le niveau d'entrée, avec trois vœux au lieu de sept et une clôture plus
précoce.

L'enjeu est concret : un étudiant en médecine à qui l'on annonce Hors-DAP
dépose sept vœux en décembre et perd son année sans avoir rien fait de
visiblement faux.

Source : Campus France, « Demandes de Licence 1 et écoles d'architecture
(procédure DAP) », consulté en octobre 2026.
"""

from app.data.procedures.france import famille_domaine
from app.services.roadmap_engine import (build_tree, etapes_pour_niveau,
                                         procedure_pour)


def _etapes(arbre):
    return {e["id"]: e for ph in arbre["phases"] for e in ph.get("etapes", [])}


# ------------------------------------------------- reconnaissance du domaine

def test_les_champs_de_sante_sont_reconnus():
    for d in ["Médecine", "pharmacie", "Chirurgie dentaire", "sage-femme",
              "sage femme", "PASS", "maïeutique", "Santé Médecine"]:
        assert famille_domaine(d) == "sante", d


def test_l_architecture_est_reconnue():
    for d in ["Architecture", "architecte", "ENSA Lyon", "urbanisme"]:
        assert famille_domaine(d) == "architecture", d


def test_un_domaine_ordinaire_ne_declenche_aucune_specificite():
    """La majorité des étudiants doivent voir le parcours standard. Inventer
    une spécificité pour chaque domaine serait pire que de n'en avoir aucune."""
    for d in ["Informatique", "Droit", "Lettres", "Agriculture", "", None]:
        assert famille_domaine(d) is None, d


# --------------------------------------------------- procédure applicable

def test_la_sante_releve_de_la_dap_meme_sans_mention_de_premiere_annee():
    p = procedure_pour("licence", "Médecine")
    assert p["code"] == "dap_blanche"
    assert p["voeux_max"] == 3


def test_l_architecture_releve_de_la_dap_a_tout_niveau():
    """C'est le cas le plus contre-intuitif : même en master, l'entrée en
    école d'architecture passe par la DAP jaune."""
    for niveau in ("l1_dap", "l2_l3", "master"):
        p = procedure_pour(niveau, "Architecture")
        assert p["code"] == "dap_jaune", niveau
        assert p["voeux_max"] == 3


def test_un_master_ordinaire_reste_hors_dap():
    p = procedure_pour("master", "Informatique")
    assert p["code"] == "hdap"
    assert p["voeux_max"] == 7


def test_la_premiere_annee_ordinaire_reste_en_dap_blanche():
    assert procedure_pour("l1_dap", "Droit")["code"] == "dap_blanche"


def test_la_procedure_porte_toujours_son_motif():
    """Un étudiant doit pouvoir vérifier la règle, pas seulement la subir."""
    for niveau, domaine in [("master", "Médecine"), ("l1_dap", "Droit"),
                            ("master", "Architecture"), ("master", "Lettres")]:
        assert procedure_pour(niveau, domaine)["motif"].strip()


# ------------------------------------------- effet sur les étapes affichées

def test_l_architecture_change_le_test_de_langue_et_la_candidature():
    etapes = {e["id"]: e for e in etapes_pour_niveau("master", "Architecture")}
    assert "TCF DAP" in etapes["langue"]["label"]
    assert "DAP jaune" in etapes["voeux"]["label"]
    assert any("travaux" in d.lower() for d in etapes["voeux"]["docs"])


def test_les_filieres_artistiques_demandent_un_dossier_de_travaux():
    etapes = {e["id"]: e for e in etapes_pour_niveau("master", "Musique")}
    assert any("portfolio" in d.lower() or "travaux" in d.lower()
               for d in etapes["dossier"]["docs"])


def test_le_domaine_ecrase_le_niveau_et_non_l_inverse():
    """L'ordre d'application est ce qui permet aux deux cas particuliers de
    corriger la règle générale."""
    etapes = {e["id"]: e for e in etapes_pour_niveau("master", "Médecine")}
    assert "DAP blanche" in etapes["voeux"]["label"]


def test_un_domaine_sans_specificite_laisse_le_parcours_du_niveau():
    ordinaire = {e["id"]: e for e in etapes_pour_niveau("master", "Informatique")}
    sans_domaine = {e["id"]: e for e in etapes_pour_niveau("master")}
    assert ordinaire["voeux"]["label"] == sans_domaine["voeux"]["label"]


def test_le_nombre_d_etapes_ne_change_jamais():
    """L'entonnoir adapte le contenu, il n'ajoute ni ne retire d'étape : la
    progression de l'étudiant resterait cohérente s'il changeait de domaine."""
    for domaine in [None, "Médecine", "Architecture", "Musique", "Commerce"]:
        assert len(etapes_pour_niveau("master", domaine)) == 14, domaine


def test_la_feuille_de_route_porte_la_procedure_applicable():
    arbre = build_tree("public", "master", domaine="Architecture")
    assert arbre["procedure"]["code"] == "dap_jaune"
    assert arbre["domaine"] == "Architecture"
    assert "DAP jaune" in _etapes(arbre)["voeux"]["label"]
