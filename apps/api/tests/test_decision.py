import pytest

from tests.test_plants import NOUVELLE, client  # noqa: F401

BODY = {"stade": "Floraison", "type_sol": "Limoneux", "surface_parcelle_m2": 500,
        "ph": 6.3, "humidite_sol_pct": 50, "temperature_sol_c": 26, "azote_N_mgkg": 60, "phosphore_P_mgkg": 30,
        "potassium_K_mgkg": 160, "conductivite_ec_dsm": 0.9,
        "temperature_air_c": 30, "humidite_air_pct": 50, "prevision_pluie_6h_mm": 0}


@pytest.fixture()
def plante(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DIAGNOSTIC_MODEL_PATH", "/chemin/inexistant.joblib")
    monkeypatch.setenv("IRRIGATION_MODEL_PATH", "/chemin/inexistant.joblib")
    c, _ = client
    return c, c.post("/plants", json=NOUVELLE).json()["id"]


def decider(c, pid, **modif):
    r = c.post("/decision/parcelle", json={"plant_id": pid, **BODY, **modif})
    assert r.status_code == 200, r.text
    return r.json()


def test_le_diagnostic_vient_avant_l_irrigation(plante):
    c, pid = plante
    d = decider(c, pid)
    assert d["ordre"][0].startswith("1. Diagnostic") and d["ordre"][1].startswith("2. Calcul")
    assert d["etape_1_diagnostic"]["etat_sante"] == "Saine"
    assert d["etape_2_irrigation"]["vanne_ouverte"] and d["etape_2_irrigation"]["ajustement"] is None
    assert "Concombre" in d["resume_agriculteur"]


def test_sol_trop_chaud_augmente_l_eau(plante):
    c, pid = plante
    normal = decider(c, pid)["etape_2_irrigation"]["besoin_L_parcelle_jour"]
    d = decider(c, pid, temperature_sol_c=40)
    assert d["etape_1_diagnostic"]["etat_sante"] == "Stress thermique"
    assert d["etape_2_irrigation"]["besoin_L_parcelle_jour"] == pytest.approx(normal * 1.2, rel=0.01)
    assert "trop chaud" in d["etape_2_irrigation"]["ajustement"]
    assert "avant 9 h" in d["resume_agriculteur"]


def test_sol_trop_humide_donc_risque_de_maladie_pas_d_arrosage(plante):
    c, pid = plante
    d = decider(c, pid, humidite_sol_pct=92)
    assert d["etape_1_diagnostic"]["etat_sante"] == "Attaque Fongique/Parasitaire"
    assert not d["etape_2_irrigation"]["vanne_ouverte"]
    assert any("Arrachez" in a for a in d["etape_1_diagnostic"]["actions"])


def test_carence_en_azote_ne_change_pas_l_eau_mais_donne_la_dose(plante):
    c, pid = plante
    normal = decider(c, pid)["etape_2_irrigation"]["besoin_L_parcelle_jour"]
    d = decider(c, pid, azote_N_mgkg=12)
    assert d["etape_1_diagnostic"]["etat_sante"] == "Carence en N"
    assert d["etape_2_irrigation"]["besoin_L_parcelle_jour"] == pytest.approx(normal, rel=1e-6)
    assert "urée" in d["etape_1_diagnostic"]["actions"][0] and "500 m²" in d["etape_1_diagnostic"]["actions"][0]


def test_sel_en_exces_ajoute_de_l_eau_sauf_si_pluie(plante):
    c, pid = plante
    normal = decider(c, pid)["etape_2_irrigation"]["besoin_L_parcelle_jour"]
    sale = decider(c, pid, conductivite_ec_dsm=3.5)["etape_2_irrigation"]
    assert sale["besoin_L_parcelle_jour"] == pytest.approx(normal * 1.15, rel=0.01) and "sel" in sale["ajustement"]
    assert decider(c, pid, conductivite_ec_dsm=3.5, prevision_pluie_6h_mm=3)["etape_2_irrigation"]["ajustement"] is None


def test_pluie_forte_et_erreurs(plante):
    c, pid = plante
    d = decider(c, pid, prevision_pluie_6h_mm=9)
    assert d["etape_2_irrigation"]["code_decision"] == "pluie_forte" and "pluie" in d["resume_agriculteur"].lower()
    assert c.post("/decision/parcelle", json={"plant_id": 999, **BODY}).status_code == 404
    assert c.post("/decision/parcelle", json={"plant_id": pid, **BODY, "stade": "Repos"}).status_code == 422
    c.delete(f"/plants/{pid}")
    assert c.post("/decision/parcelle", json={"plant_id": pid, **BODY}).status_code == 409


def test_resume_coherent_quand_on_n_arrose_pas(plante):
    c, pid = plante
    d = decider(c, pid, temperature_sol_c=40, humidite_sol_pct=80)       # sol chaud mais déjà humide
    assert d["etape_1_diagnostic"]["etat_sante"] == "Stress thermique"
    assert not d["etape_2_irrigation"]["vanne_ouverte"]
    assert "on ajoute" not in d["resume_agriculteur"] and "Pas d'arrosage" in d["resume_agriculteur"]
    assert "À faire en priorité" in d["resume_agriculteur"]            # le conseil de paillage reste visible
