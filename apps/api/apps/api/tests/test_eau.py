from datetime import datetime, timedelta

from app import models_parcelles as mp
from app import simulation as sim
from app.engine import eau
from tests.test_parcelles import ferme  # noqa: F401
from tests.test_plants import client  # noqa: F401

DEBUT = datetime(2026, 10, 7, 23, 0)          # = 8 octobre 0 h à Kinshasa (UTC+1)
PARCELLE = [{"id": 1, "nom": "P", "surface_m2": 900, "kc": 1.0}]      # classique : 1 × 5 × 900 / 0,9 = 5 000 L/jour


def ev(action, h, minutes=60, litres=3000, pid=1):
    return {"parcelle_id": pid, "action": action, "minutes": minutes, "litres": litres, "at": DEBUT + timedelta(hours=h)}


def test_base_classique_et_litres_reels():
    b = eau.bilan(PARCELLE, [ev("ouvrir", 6)], DEBUT, DEBUT + timedelta(days=2))
    assert b["comparaison_fiable"] and b["jours"] == 2 and b["ferme"]["classiques"] == 10000 and b["ferme"]["reels"] == 3000
    assert b["ferme"]["economie"] == 7000 and b["ferme"]["economie_pct"] == 70
    assert [j["date"] for j in b["par_jour"]] == ["2026-10-08", "2026-10-09"]
    assert [j["reels"] for j in b["par_jour"]] == [3000, 0] and [j["classiques"] for j in b["par_jour"]] == [5000, 5000]


def test_vanne_fermee_plus_tot_ou_periode_coupee_ne_compte_que_le_reel():
    ferme_tot = eau.bilan(PARCELLE, [ev("ouvrir", 6), ev("fermer", 6.5, 0, 0)], DEBUT, DEBUT + timedelta(days=1))
    assert ferme_tot["ferme"]["reels"] == 1500                       # 30 min sur 60 : la moitié des litres prévus
    coupe = eau.bilan(PARCELLE, [ev("ouvrir", 23.5)], DEBUT, DEBUT + timedelta(days=1))
    assert coupe["ferme"]["reels"] == 1500                           # la vanne vient de s'ouvrir : seule la 1re demi-heure
    avant = eau.bilan(PARCELLE, [ev("ouvrir", -0.5)], DEBUT, DEBUT + timedelta(days=1))
    assert avant["ferme"]["reels"] == 1500                           # 30 min avant le début : seule la 2e demi-heure


def test_arrosage_a_cheval_sur_minuit_est_reparti_par_jour_local():
    b = eau.bilan(PARCELLE, [ev("ouvrir", 23)], DEBUT, DEBUT + timedelta(days=2))     # 23 h → minuit : 1 h, tout le 8 octobre
    assert [j["reels"] for j in b["par_jour"]] == [3000, 0]
    b = eau.bilan(PARCELLE, [ev("ouvrir", 23.5)], DEBUT, DEBUT + timedelta(days=2))   # 30 min avant minuit, 30 min après
    assert [j["reels"] for j in b["par_jour"]] == [1500, 1500]


def test_sans_donnees_pas_d_economie_inventee():
    b = eau.bilan(PARCELLE, [], DEBUT, DEBUT)
    assert b["jours"] == 0 and b["ferme"]["economie_pct"] is None and b["par_jour"] == []


def test_endpoint_apres_simulation(client, ferme, monkeypatch):           # noqa: F811
    c, Session = client
    monkeypatch.setattr(sim, "SECONDES", 5.0)
    monkeypatch.setattr(sim, "PROBA_PLUIE", 0.0)
    monkeypatch.setitem(mp._horloge, "simulee", None)
    for k, v in {"actif": True, "horloge": datetime(2026, 10, 8, 5, 0), "pas": 0}.items():
        monkeypatch.setitem(sim.ETAT, k, v)
    sim._pluie.clear()
    for _ in range(36):                                          # 6 h simulées, dont la plage d'arrosage du matin
        sim.avancer(Session)
    r = c.get("/eau?jours=7").json()
    assert 0.2 < r["jours"] < 0.3 and r["ferme"]["reels"] > 0
    assert r["comparaison_fiable"] is False                      # moins d'un jour : un seul arrosage du matin fausse la comparaison
    assert len(r["parcelles"]) == 10 and abs(sum(p["reels"] for p in r["parcelles"]) - r["ferme"]["reels"]) <= 5
    assert c.get("/eau?jours=0").status_code == 422
