import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import creer_admin_initial, ouvrir_session
from app.database import Base, get_db
from app.main import app
from app.models_auth import Utilisateur
from app.seed import seed_catalogue

NOUVELLE = {
    "nom": "Concombre", "categorie": "Légumes & Maraîchage",
    "kc_germination": 0.6, "kc_vegetative": 0.85, "kc_floraison": 1.0, "kc_fructification": 0.75,
    "ph_min": 5.8, "ph_max": 6.8, "n_min": 40, "n_max": 80, "p_min": 20, "p_max": 40,
    "k_min": 130, "k_max": 220, "ec_max_dsm": 2.0, "humidite_sol_min": 60, "humidite_sol_max": 80,
    "temp_opt_min": 20, "temp_opt_max": 30, "tolerance_hydrique": 2,
    "densite_plants_ha": 25000, "debit_plant_lph": 4, "varietes": ["Marketmore", "Locale"],
}


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override
    os.environ["ADMIN_MOT_DE_PASSE"] = "motdepasse-test"
    with Session() as db:                                  # les tests sont connectés en administrateur par défaut
        creer_admin_initial(db)
        jeton, _ = ouvrir_session(db, db.query(Utilisateur).first())
    tc = TestClient(app)
    tc.headers["Authorization"] = f"Bearer {jeton}"
    yield tc, Session
    app.dependency_overrides.clear()


def test_seed_charge_les_13_plantes(client):
    c, Session = client
    with Session() as db:
        assert seed_catalogue(db) == 13
        assert seed_catalogue(db) == 0  # idempotent
    assert len(c.get("/plants").json()) == 13


def test_ajout_dune_plante_et_doublon(client):
    c, _ = client
    r = c.post("/plants", json=NOUVELLE)
    assert r.status_code == 201
    body = r.json()
    assert body["params_version"] == 1 and body["source"] == "user"
    assert sorted(v["nom"] for v in body["varietes"]) == ["Locale", "Marketmore"]
    assert c.post("/plants", json=NOUVELLE).status_code == 409


def test_validation_refuse_les_plages_incoherentes(client):
    c, _ = client
    assert c.post("/plants", json={**NOUVELLE, "ph_min": 7.5}).status_code == 422
    assert c.post("/plants", json={**NOUVELLE, "kc_floraison": 3}).status_code == 422


def test_modification_incremente_la_version_et_journalise(client):
    c, _ = client
    pid = c.post("/plants", json=NOUVELLE).json()["id"]
    r = c.put(f"/plants/{pid}", json={"kc_floraison": 1.1})
    assert r.status_code == 200 and r.json()["params_version"] == 2
    assert r.json()["kc_floraison"] == 1.1
    hist = c.get(f"/plants/{pid}/historique").json()
    assert [h["version"] for h in hist] == [1, 2]
    assert hist[0]["snapshot"]["kc_floraison"] == 1.0  # ancien état conservé


def test_modification_incoherente_refusee(client):
    c, _ = client
    pid = c.post("/plants", json=NOUVELLE).json()["id"]
    assert c.put(f"/plants/{pid}", json={"ph_max": 5.0}).status_code == 422
    assert c.put(f"/plants/{pid}", json={"champ_inconnu": 1}).status_code == 422
    assert c.get(f"/plants/{pid}").json()["params_version"] == 1  # rien n'a changé


def test_suppression_logique_et_reactivation(client):
    c, _ = client
    pid = c.post("/plants", json=NOUVELLE).json()["id"]
    assert c.delete(f"/plants/{pid}").status_code == 204
    assert c.get("/plants").json() == []
    assert len(c.get("/plants?include_inactive=true").json()) == 1
    assert c.post(f"/plants/{pid}/reactivate").json()["is_active"] is True


def test_varietes(client):
    c, _ = client
    pid = c.post("/plants", json=NOUVELLE).json()["id"]
    r = c.post(f"/plants/{pid}/varietes", json={"nom": "Lisse verte"})
    assert r.status_code == 201
    assert c.post(f"/plants/{pid}/varietes", json={"nom": "Lisse verte"}).status_code == 409
    vid = r.json()["varietes"][0]["id"]
    assert c.delete(f"/plants/{pid}/varietes/{vid}").status_code == 200
