import pytest

from tests.test_parcelles import ferme  # noqa: F401
from tests.test_plants import client  # noqa: F401


def test_position_gps_ajout_modification_retrait(ferme):
    p = ferme.post("/parcelles", json={"nom": "Parcelle G1", "surface_m2": 1000, "plant_id": 2,
                                       "latitude": -4.3, "longitude": 15.3}).json()
    assert (p["latitude"], p["longitude"]) == (-4.3, 15.3)
    r = ferme.put(f"/parcelles/{p['id']}", json={"latitude": -4.31, "longitude": 15.32}).json()
    assert (r["latitude"], r["longitude"]) == (-4.31, 15.32)
    r = ferme.put(f"/parcelles/{p['id']}", json={"latitude": None, "longitude": None}).json()
    assert r["latitude"] is None and r["longitude"] is None


def test_position_gps_incomplete_ou_impossible_refusee(ferme):
    assert ferme.post("/parcelles", json={"nom": "G2", "surface_m2": 10, "plant_id": 2, "latitude": -4.3}).status_code == 422
    assert ferme.post("/parcelles", json={"nom": "G3", "surface_m2": 10, "plant_id": 2, "latitude": 95, "longitude": 10}).status_code == 422
    pid = ferme.get("/parcelles").json()[0]["id"]
    assert ferme.put(f"/parcelles/{pid}", json={"latitude": -4.3}).status_code == 422


def test_parcelles_sans_position_par_defaut(ferme):
    assert all(p["latitude"] is None for p in ferme.get("/parcelles").json())


@pytest.mark.parametrize("page", ["carte.html", "langues.js", "langues-dict.js"])
def test_pages_carte_et_langues_servies(ferme, page):
    r = ferme.get(f"/tableau-de-bord/{page}")
    assert r.status_code == 200 and len(r.text) > 500
