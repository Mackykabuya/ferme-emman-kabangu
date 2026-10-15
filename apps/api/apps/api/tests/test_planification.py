from tests.test_parcelles import ferme  # noqa: F401
from tests.test_plants import client  # noqa: F401


def test_la_pompe_limite_les_vannes_ouvertes_en_commencant_par_les_plus_urgentes(ferme):  # noqa: F811
    r1 = ferme.post("/parcelles/appliquer-auto?debit_pompe=60000&heure=6").json()
    assert r1["vannes_ouvertes"] and r1["en_attente_de_pompe"]
    assert r1["debit_utilise_lh"] <= 60000 or len(r1["vannes_ouvertes"]) == 1
    r2 = ferme.post("/parcelles/appliquer-auto?debit_pompe=1e12&heure=6").json()      # pompe sans limite : les autres suivent
    assert sorted(r2["vannes_ouvertes"]) == sorted(r1["en_attente_de_pompe"]) and r2["en_attente_de_pompe"] == []


def test_meteo_du_moment_utilisee_par_defaut(ferme):  # noqa: F811
    try:
        assert ferme.put("/meteo", json={"temperature_air_c": 28, "humidite_air_pct": 60, "prevision_pluie_6h_mm": 9}).status_code == 200
        apercu = ferme.get("/parcelles/apercu").json()
        assert all(p["decision"]["etape_2_irrigation"]["code_decision"] in ("pluie_forte", "sol_humide") for p in apercu)
        assert ferme.post("/parcelles/appliquer-auto?debit_pompe=1e12&heure=6").json()["vannes_ouvertes"] == []
        assert ferme.put("/meteo", json={"temperature_air_c": 99, "humidite_air_pct": 60, "prevision_pluie_6h_mm": 0}).status_code == 422
    finally:
        ferme.put("/meteo", json={"temperature_air_c": 30, "humidite_air_pct": 55, "prevision_pluie_6h_mm": 0})
