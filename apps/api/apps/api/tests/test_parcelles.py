import pytest

from app.seed import seed_catalogue
from app.seed_parcelles import seed_parcelles
from tests.test_plants import client  # noqa: F401


@pytest.fixture()
def ferme(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DIAGNOSTIC_MODEL_PATH", "/inexistant")
    monkeypatch.setenv("IRRIGATION_MODEL_PATH", "/inexistant")
    c, Session = client
    with Session() as db:
        seed_catalogue(db)
        assert seed_parcelles(db) == 10
    return c


def test_dix_parcelles_dix_cultures_et_apercu(ferme):
    liste = ferme.get("/parcelles").json()
    assert len(liste) == 10 and len({p["plante"] for p in liste}) == 10
    assert sum(p["surface_m2"] for p in liste) == 47500
    apercu = ferme.get("/parcelles/apercu?pluie=0").json()
    etats = {p["nom"]: p["decision"]["etape_1_diagnostic"]["etat_sante"] for p in apercu}
    assert etats["Parcelle A1"] == "Carence en N" and etats["Parcelle C1"] == "Stress thermique"
    assert etats["Parcelle B1"] == "Attaque Fongique/Parasitaire" and not apercu[2]["decision"]["etape_2_irrigation"]["vanne_ouverte"]


def test_ajout_modification_suppression(ferme):
    r = ferme.post("/parcelles", json={"nom": "Parcelle F1", "surface_m2": 2500, "plant_id": 2})
    assert r.status_code == 201 and r.json()["mode"] == "auto"
    assert ferme.post("/parcelles", json={"nom": "Parcelle F1", "surface_m2": 10, "plant_id": 2}).status_code == 409
    assert ferme.post("/parcelles", json={"nom": "Parcelle F2", "surface_m2": 10, "plant_id": 999}).status_code == 404
    pid = r.json()["id"]
    assert ferme.put(f"/parcelles/{pid}", json={"mode": "manuel", "mesures": {"ph": 5.0}}).json()["mesures"]["ph"] == 5.0
    assert ferme.delete(f"/parcelles/{pid}").status_code == 204 and ferme.get(f"/parcelles/{pid}").status_code == 404


def test_vanne_manuelle_duree_limitee_et_historique(ferme):
    pid = ferme.get("/parcelles").json()[0]["id"]
    assert ferme.post(f"/parcelles/{pid}/vanne", json={"action": "ouvrir", "duree_min": 500}).status_code == 422
    assert ferme.post(f"/parcelles/{pid}/vanne", json={"action": "ouvrir", "duree_min": 20}).json()["vanne_ouverte"]
    assert not ferme.post(f"/parcelles/{pid}/vanne", json={"action": "fermer"}).json()["vanne_ouverte"]
    h = ferme.get(f"/parcelles/{pid}/historique").json()
    assert [e["action"] for e in h] == ["fermer", "ouvrir"] and h[1]["litres"] > 0


def test_mode_auto_n_ouvre_que_les_parcelles_auto_qui_ont_soif(ferme):
    ids = {p["nom"]: p["id"] for p in ferme.get("/parcelles").json()}
    ferme.put(f"/parcelles/{ids['Parcelle A2']}", json={"mode": "manuel"})
    ouvertes = ferme.post("/parcelles/appliquer-auto?debit_pompe=1e12&heure=6").json()["vannes_ouvertes"]
    assert "Parcelle A1" in ouvertes and "Parcelle A2" not in ouvertes     # A2 est en manuel
    assert "Parcelle B1" not in ouvertes and "Parcelle D1" not in ouvertes  # sol déjà humide
    assert ferme.post("/parcelles/appliquer-auto?debit_pompe=1e12&heure=6").json()["vannes_ouvertes"] == []   # déjà ouvertes
    assert ferme.post("/parcelles/appliquer-auto?debit_pompe=1e12&heure=6&pluie=9").json()["vannes_ouvertes"] == []
