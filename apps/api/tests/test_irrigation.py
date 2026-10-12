from types import SimpleNamespace

import pytest

from app.engine.irrigation import et0_hargreaves, estimer_irrigation
from tests.test_plants import NOUVELLE, client  # noqa: F401  (fixture réutilisée)

PIMENT = SimpleNamespace(nom="Piment", kc_germination=0.6, kc_vegetative=0.85, kc_floraison=1.05,
                         kc_fructification=0.9, humidite_sol_min=55, humidite_sol_max=75,
                         densite_plants_ha=20000, debit_plant_lph=4, tolerance_hydrique=2)


def calc(**kw):
    args = dict(stade="Floraison", t_air=30, humidite_air=50, humidite_sol=40, type_sol="Limoneux",
                pluie_6h_mm=0, surface_parcelle_m2=1000)
    args.update(kw)
    return estimer_irrigation(PIMENT, **args)


@pytest.fixture(autouse=True)
def sans_modele_ml(monkeypatch):
    monkeypatch.setenv("IRRIGATION_MODEL_PATH", "/chemin/inexistant.joblib")
    monkeypatch.setenv("DIAGNOSTIC_MODEL_PATH", "/chemin/inexistant.joblib")


def test_et0_dans_une_plage_realiste():
    assert 3.5 < et0_hargreaves(27, 70) < 6.5


def test_sol_sec_declenche_une_irrigation_coherente():
    d = calc()
    assert d.vanne_ouverte and d.besoin_L_par_plant_jour > 0 and d.code_decision == "irrigation"
    assert d.nb_plants == 2000 and d.methode == "formule"
    assert d.besoin_L_parcelle_jour == pytest.approx(d.besoin_L_par_plant_jour * 2000, rel=1e-3)
    assert 0 < d.duree_min <= 240
    assert "Piment" in d.resume and "litres" in d.resume


def test_seuil_de_declenchement_au_milieu_de_la_plage():
    # plage idéale 55-75 % : milieu = 65 %
    assert not calc(humidite_sol=70).vanne_ouverte      # encore confortable : on n'arrose pas
    assert not calc(humidite_sol=80).vanne_ouverte
    assert calc(humidite_sol=60).vanne_ouverte          # sous le milieu : on arrose
    assert calc(humidite_sol=50).besoin_L_par_plant_jour > calc(humidite_sol=63).besoin_L_par_plant_jour


def test_pluie_forte_reporte_et_pluie_legere_reduit():
    base = calc()
    forte = calc(pluie_6h_mm=6)
    assert not forte.vanne_ouverte and forte.code_decision == "pluie_forte" and "pluie" in forte.motif
    legere = calc(pluie_6h_mm=3)
    assert legere.vanne_ouverte and legere.code_decision == "pluie_legere"
    assert legere.besoin_L_par_plant_jour == pytest.approx(base.besoin_L_par_plant_jour / 2, rel=1e-3)


def test_sol_sableux_demande_plus_que_argileux():
    assert calc(type_sol="Sableux").besoin_L_par_plant_jour > calc(type_sol="Argileux").besoin_L_par_plant_jour


def test_le_diagnostic_corrige_le_volume():
    base = calc().besoin_L_par_plant_jour
    chaud = calc(etat_sante="Stress thermique")
    assert chaud.besoin_L_par_plant_jour == pytest.approx(base * 1.2, rel=1e-3)
    assert "trop chaud" in chaud.ajustement and "avant 9 h" in chaud.conseil_horaire
    malade = calc(etat_sante="Attaque Fongique/Parasitaire")
    assert malade.besoin_L_par_plant_jour == pytest.approx(base * 0.6, rel=1e-3)
    assert "au pied" in malade.conseil_horaire
    sale = calc(salinite_elevee=True)
    assert sale.besoin_L_par_plant_jour == pytest.approx(base * 1.15, rel=1e-3) and "sel" in sale.ajustement
    # pas de lavage des sels si de la pluie arrive
    assert calc(salinite_elevee=True, pluie_6h_mm=3).ajustement is None
    assert calc(etat_sante="Carence en N").besoin_L_par_plant_jour == pytest.approx(base, rel=1e-6)
    # pas d'ajustement affiché quand on n'arrose pas
    assert calc(etat_sante="Stress thermique", humidite_sol=80).ajustement is None


def test_messages_en_francais_avec_virgule():
    d = calc(type_sol="Sableux")
    assert "," in d.resume and "litre(s)" not in d.resume and "." not in d.resume.split("par plant")[0].split("(")[-1]


def test_modele_ml_avec_garde_fou():
    base = calc()
    etc_litres = base.et0_mm_jour * base.kc * 0.5      # 0,5 m² par plant (20 000 plants/ha)
    ratio_formule = base.besoin_L_par_plant_jour / etc_litres
    proche = calc(predire_ratio=lambda f: ratio_formule * 1.1)
    assert proche.methode == "ml" and proche.besoin_L_par_plant_jour == pytest.approx(base.besoin_L_par_plant_jour * 1.1, rel=0.01)
    absurde = calc(predire_ratio=lambda f: ratio_formule * 5)
    assert absurde.methode == "formule (garde-fou)" and absurde.besoin_L_par_plant_jour == base.besoin_L_par_plant_jour
    # le ML n'intervient jamais quand la vanne est fermée
    assert calc(humidite_sol=80, predire_ratio=lambda f: 99).besoin_L_parcelle_jour == 0


def test_stade_inconnu_refuse():
    with pytest.raises(ValueError):
        calc(stade="Repos")


def test_endpoint_plante_ajoutee_dynamiquement(client):  # noqa: F811
    c, _ = client
    pid = c.post("/plants", json=NOUVELLE).json()["id"]
    body = {"plant_id": pid, "stade": "Floraison", "temperature_air_c": 30, "humidite_air_pct": 50,
            "humidite_sol_pct": 45, "type_sol": "Limoneux", "surface_parcelle_m2": 500}
    r = c.post("/irrigation/recommandation", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["plante"] == "Concombre" and out["vanne_ouverte"] and out["params_version"] == 1
    assert "Concombre" in out["resume"] and out["conseil_horaire"]
    c.put(f"/plants/{pid}", json={"kc_floraison": 1.3})
    out2 = c.post("/irrigation/recommandation", json=body).json()
    assert out2["params_version"] == 2 and out2["besoin_L_parcelle_jour"] > out["besoin_L_parcelle_jour"]
    c.delete(f"/plants/{pid}")
    assert c.post("/irrigation/recommandation", json=body).status_code == 409
    assert c.post("/irrigation/recommandation", json={**body, "plant_id": 999}).status_code == 404
    assert c.post("/irrigation/recommandation", json={**body, "stade": "Repos"}).status_code == 422
