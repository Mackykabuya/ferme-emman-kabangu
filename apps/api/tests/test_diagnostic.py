from types import SimpleNamespace

import pytest

from app.engine import conseils as cs
from app.engine import diagnostic as dg
from tests.test_plants import NOUVELLE, client  # noqa: F401

PIMENT = SimpleNamespace(nom="Piment", ph_min=5.8, ph_max=6.8, n_min=40, n_max=80, p_min=20, p_max=40,
                         k_min=120, k_max=200, ec_max_dsm=1.5, humidite_sol_min=55, humidite_sol_max=75,
                         temp_opt_min=22, temp_opt_max=30)
IDEAL = {"ph": 6.3, "humidite_sol": 65, "temperature_sol": 26, "N": 60, "P": 30, "K": 160,
         "ec": 0.9, "type_sol": "Limoneux"}
MODELE_PRESENT = dg.MODELE_PAR_DEFAUT.exists()
BODY = {"type_sol": "Limoneux", "ph": 6.3, "humidite_sol_pct": 65, "temperature_sol_c": 26,
        "azote_N_mgkg": 60, "phosphore_P_mgkg": 30, "potassium_K_mgkg": 160, "conductivite_ec_dsm": 0.9}
JARGON = ["pH", " EC", "Kc", "lessivage", "fractionn", "amendement", "kg N/ha", "ET0", "mg/kg"]


@pytest.fixture()
def sans_modele(monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_MODEL_PATH", "/chemin/inexistant.joblib")


def test_variables_relatives_valent_environ_1_pour_une_plante_ideale():
    f = dg.features_dict(PIMENT, IDEAL)
    assert f["ph_ecart"] == pytest.approx(0) and f["humidite_ecart"] == pytest.approx(0)
    assert f["n_ratio"] == pytest.approx(1) and f["p_ratio"] == pytest.approx(1) and f["k_ratio"] == pytest.approx(1)
    assert f["humidite_exces"] == 0 and f["temp_exces"] == 0 and f["sol_limoneux"] == 1
    assert len(dg.features_from(PIMENT, IDEAL)) == len(dg.FEATURES)


@pytest.mark.parametrize("modif,attendu", [
    ({}, "Saine"), ({"N": 20}, "Carence en N"), ({"P": 8}, "Carence en P"), ({"K": 50}, "Carence en K"),
    ({"temperature_sol": 38}, "Stress thermique"),
    ({"humidite_sol": 88, "temperature_sol": 26}, "Attaque Fongique/Parasitaire"),
])
def test_regles_de_secours(modif, attendu):
    assert dg.regles_diagnostic(PIMENT, {**IDEAL, **modif}) == attendu


def test_dose_en_kg_par_are_et_pour_la_parcelle():
    q = cs.quantite(2.0, 1000)
    assert "2 kg par are" in q and "20 kg pour vos 1000 m²" in q
    assert cs.quantite(0.65).startswith("environ 0,7 kg")           # virgule française
    txt = dg.recommandation(PIMENT, "Carence en N", {**IDEAL, "N": 18}, surface_m2=1000)
    assert "urée" in txt and "pour vos 1000 m²" in txt


def test_sol_sableux_donne_des_doses_plus_petites_et_plus_frequentes():
    sable = dg.recommandation(PIMENT, "Carence en N", {**IDEAL, "N": 18, "type_sol": "Sableux"})
    assert "trois petites doses" in sable
    assert "deux fois" in dg.recommandation(PIMENT, "Carence en N", {**IDEAL, "N": 18})


def test_alertes_acidite_et_sel_en_langage_simple():
    txt = dg.recommandation(PIMENT, "Saine", {**IDEAL, "ph": 4.8, "ec": 2.5})
    assert "trop acide" in txt and "chaux" in txt and "trop de sel" in txt
    c = cs.conseils_diagnostic(PIMENT, "Saine", {**IDEAL, "ph": 4.8})
    assert "point à corriger" in c["message_simple"]


@pytest.mark.parametrize("etat", dg.ETATS)
def test_aucun_jargon_dans_les_conseils(etat):
    texte = dg.recommandation(PIMENT, etat, {**IDEAL, "ph": 4.8, "ec": 2.5, "N": 18, "P": 8, "K": 50})
    for mot in JARGON:
        assert mot not in texte, f"jargon « {mot} » trouvé pour {etat}"
    c = cs.conseils_diagnostic(PIMENT, etat, IDEAL)
    assert c["message_simple"] and c["actions"] and c["a_surveiller"] is not None


def test_endpoint_sans_modele_utilise_les_regles(client, sans_modele):  # noqa: F811
    c, _ = client
    pid = c.post("/plants", json=NOUVELLE).json()["id"]
    r = c.post("/diagnostic/pedologique", json={"plant_id": pid, **BODY, "azote_N_mgkg": 10,
                                                "surface_parcelle_m2": 500})
    assert r.status_code == 200
    out = r.json()
    assert out["mode"] == "regles" and out["etat_sante"] == "Carence en N"
    assert out["etat_sante_libelle"] == "Manque d'azote (N)"
    assert out["avertissement"] and len(out["actions"]) >= 2 and "pour vos 500 m²" in out["actions"][0]
    assert "urée" in out["recommandation"]


def test_endpoint_erreurs(client, sans_modele):  # noqa: F811
    c, _ = client
    assert c.post("/diagnostic/pedologique", json={"plant_id": 999, **BODY}).status_code == 404
    pid = c.post("/plants", json=NOUVELLE).json()["id"]
    assert c.post("/diagnostic/pedologique", json={"plant_id": pid, **BODY, "ph": 20}).status_code == 422
    c.delete(f"/plants/{pid}")
    assert c.post("/diagnostic/pedologique", json={"plant_id": pid, **BODY}).status_code == 409


@pytest.mark.skipif(not MODELE_PRESENT, reason="modèle non entraîné (python ml/train_diagnostic.py)")
def test_endpoint_avec_modele_ml_et_plante_inedite(client):  # noqa: F811
    c, _ = client
    pid = c.post("/plants", json=NOUVELLE).json()["id"]      # « Concombre » : absent de l'entraînement
    sain = c.post("/diagnostic/pedologique", json={"plant_id": pid, **BODY}).json()
    assert sain["mode"] == "ml" and sain["etat_sante"] == "Saine"
    assert sain["plante_connue_du_modele"] is False and "nouvelle pour le système" in sain["avertissement"]
    assert sum(sain["probabilites"].values()) == pytest.approx(1, abs=0.01)
    carence = c.post("/diagnostic/pedologique", json={"plant_id": pid, **BODY, "azote_N_mgkg": 15}).json()
    assert carence["etat_sante"] == "Carence en N" and "urée" in carence["recommandation"]
    chaud = c.post("/diagnostic/pedologique", json={"plant_id": pid, **BODY, "temperature_sol_c": 40}).json()
    assert chaud["etat_sante"] == "Stress thermique"
