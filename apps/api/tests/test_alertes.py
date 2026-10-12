from datetime import datetime, timedelta

import pytest

from app import models_parcelles as mp
from app import simulation as sim
from app.engine import anomalies as an
from app.routers import meteo
from tests.test_parcelles import ferme  # noqa: F401
from tests.test_plants import client  # noqa: F401

T0 = datetime(2026, 10, 8, 5, 0)


def serie(valeurs, ouvertes=None):
    return [{"at": T0 + timedelta(minutes=10 * i), "mesures": dict(v), "vanne_ouverte": bool(ouvertes[i]) if ouvertes else False}
            for i, v in enumerate(valeurs)]


def normal(i):
    return {"humidite_sol_pct": 50 - i * 0.1, "ph": 6.5, "temperature_sol_c": 25 + i * 0.05}


def test_capteur_bloque_et_valeur_impossible_et_vanne():
    ok = serie([normal(i) for i in range(8)])
    assert an.analyser_parcelle("P", ok) == []
    gele = serie([normal(0)] * 8)
    assert [a["code"] for a in an.analyser_parcelle("P", gele)] == ["capteur_bloque"]
    assert an.capteur_suspect(gele) and not an.capteur_suspect(ok)
    faux = serie([normal(i) for i in range(7)] + [{**normal(7), "humidite_sol_pct": 0.0}])
    assert an.analyser_parcelle("P", faux)[0]["code"] == "valeur_impossible"
    faux2 = serie([normal(i) for i in range(7)] + [{**normal(7), "ph": 19}])
    assert an.analyser_parcelle("P", faux2)[0]["champ"] == "ph"
    # vanne ouverte, humidité qui ne monte pas
    plat = serie([{**normal(i), "humidite_sol_pct": 40 - i * 0.05} for i in range(8)], [0, 0, 1, 1, 1, 1, 0, 0])   # fermée depuis : l'alerte reste
    assert [a["code"] for a in an.analyser_parcelle("P", plat)] == ["vanne_sans_effet"]
    monte = serie([{**normal(i), "humidite_sol_pct": 40 + i * 2} for i in range(6)], [0, 0, 1, 1, 1, 1])
    assert an.analyser_parcelle("P", monte) == []
    # pompe
    assert an.analyser_parcelle("P", ok, 176000, 120000)[0]["code"] == "pompe_trop_faible"
    assert an.analyser_parcelle("P", ok, 100000, 120000) == []


def test_messages_sans_jargon():
    textes = " ".join(a["titre"] + a["message"] + a["conseil"] for hist in (serie([normal(0)] * 8), serie([{**normal(0), "ph": 30}] * 8))
                      for a in an.analyser_parcelle("Parcelle A1", hist))
    for mot in ("EC ", "ETc", "ET0", "dS/m", "capteur_bloque"):
        assert mot not in textes
    assert "Parcelle A1" in textes


@pytest.fixture
def simu(client, ferme, monkeypatch):  # noqa: F811
    c, Session = client
    sauve = (dict(meteo.METEO), dict(meteo.INFO))
    monkeypatch.setattr(sim, "SECONDES", 5.0)
    monkeypatch.setattr(sim, "PROBA_PLUIE", 0.0)
    monkeypatch.setitem(mp._horloge, "simulee", None)
    monkeypatch.setattr(sim, "PANNES", {})
    monkeypatch.setattr(sim, "_reel", {})
    for k, v in {"actif": True, "horloge": datetime(2026, 10, 8, 5, 0), "pas": 0}.items():
        monkeypatch.setitem(sim.ETAT, k, v)
    sim._pluie.clear()
    yield c, Session
    meteo.METEO.clear(); meteo.METEO.update(sauve[0]); meteo.INFO.clear(); meteo.INFO.update(sauve[1])


def test_aucune_fausse_alerte_en_fonctionnement_normal(simu):
    c, Session = simu
    for _ in range(40):
        sim.avancer(Session)
    urgentes = [a for a in c.get("/alertes").json()["alertes"] if a["gravite"] != "info"]
    assert urgentes == [], urgentes


def test_pannes_injectees_detectees_puis_reparees(simu):
    c, Session = simu
    ids = {p["nom"]: p["id"] for p in c.get("/parcelles").json()}
    for _ in range(3):
        sim.avancer(Session)
    assert c.post("/simulation/panne", json={"parcelle_id": ids["Parcelle B2"], "type": "bloque"}).status_code == 200
    assert c.post("/simulation/panne", json={"parcelle_id": ids["Parcelle C2"], "type": "aberrant"}).status_code == 200
    assert c.post("/simulation/panne", json={"parcelle_id": 9999, "type": "bloque"}).status_code == 404
    assert c.post("/simulation/panne", json={"parcelle_id": ids["Parcelle C2"], "type": "n_importe_quoi"}).status_code == 422
    for _ in range(8):
        sim.avancer(Session)
    codes = {(a["parcelle"], a["code"]) for a in c.get("/alertes").json()["alertes"]}
    assert ("Parcelle B2", "capteur_bloque") in codes and ("Parcelle C2", "valeur_impossible") in codes
    assert c.get("/simulation").json()["pannes"]
    # le sol réel continue d'évoluer pendant la panne ; après réparation, la lecture le retrouve
    reel = sim._reel[ids["Parcelle C2"]]["humidite_sol_pct"]
    assert 5 <= reel <= 95
    c.delete(f"/simulation/panne/{ids['Parcelle B2']}"); c.delete(f"/simulation/panne/{ids['Parcelle C2']}")
    for _ in range(8):
        sim.avancer(Session)
    restantes = [a for a in c.get("/alertes").json()["alertes"] if a["gravite"] != "info"]
    assert restantes == []
    assert c.get(f"/parcelles/{ids['Parcelle C2']}").json()["mesures"]["humidite_sol_pct"] > 1


def test_arrosage_auto_suspendu_sur_capteur_douteux(simu):
    c, Session = simu
    ids = {p["nom"]: p["id"] for p in c.get("/parcelles").json()}
    # Parcelle A2 : sol très sec + capteur muet -> on n'arrose pas sur une valeur douteuse
    for _ in range(2):
        sim.avancer(Session)
    for nom in ids:
        c.post("/simulation/panne", json={"parcelle_id": ids[nom], "type": "bloque"})
    for _ in range(8):
        sim.avancer(Session)
    r = c.post("/parcelles/appliquer-auto?heure=6").json()
    assert r["vannes_ouvertes"] == [] and len(r["capteur_douteux"]) >= 8       # (une vanne déjà ouverte avant la panne n'est pas concernée)


def test_vanne_sans_effet_detectee(simu):
    c, Session = simu
    ids = [p["id"] for p in c.get("/parcelles").json()]
    for i in ids:
        c.post("/simulation/panne", json={"parcelle_id": i, "type": "vanne"})
    for _ in range(30):
        sim.avancer(Session)
    codes = {a["code"] for a in c.get("/alertes").json()["alertes"]}
    assert "vanne_sans_effet" in codes


def test_panne_refusee_si_simulation_desactivee(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(sim, "SECONDES", 0.0)
    assert c.post("/simulation/panne", json={"parcelle_id": 1, "type": "bloque"}).status_code == 409
