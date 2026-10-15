from datetime import datetime

from app import models_parcelles as mp
from app import simulation as sim
from app.routers import meteo
from tests.test_parcelles import ferme  # noqa: F401
from tests.test_plants import client  # noqa: F401


def test_la_simulation_fait_evoluer_mesures_historique_et_vannes(client, ferme, monkeypatch):  # noqa: F811
    c, Session = client
    sauve = (dict(meteo.METEO), dict(meteo.INFO))
    monkeypatch.setattr(sim, "SECONDES", 5.0)
    monkeypatch.setattr(sim, "PROBA_PLUIE", 0.0)
    monkeypatch.setitem(mp._horloge, "simulee", None)                      # restauré à la fin du test
    for k, v in {"actif": True, "horloge": datetime(2026, 10, 8, 5, 0), "pas": 0}.items():   # 5 h UTC = 6 h à Kinshasa
        monkeypatch.setitem(sim.ETAT, k, v)
    sim._pluie.clear()
    try:
        parcelles = c.get("/parcelles").json()
        avant = {p["id"]: p["mesures"]["humidite_sol_pct"] for p in parcelles}
        for _ in range(30):                                                 # 5 heures simulées, de 6 h à 11 h (heure locale)
            sim.avancer(Session)
        historiques = {p["id"]: c.get(f"/parcelles/{p['id']}/mesures").json() for p in parcelles}
        h = historiques[parcelles[0]["id"]]
        assert len(h) == 30 and h[0]["date"] == "2026-10-08T05:00:00" and h[1]["date"] == "2026-10-08T05:10:00"
        assert h[-1]["date"] == "2026-10-08T09:50:00"

        apres = {p["id"]: p["mesures"]["humidite_sol_pct"] for p in c.get("/parcelles").json()}
        assert all(avant[i] != apres[i] for i in avant), "toutes les parcelles doivent évoluer"

        # l'évaporation est bien prise en compte : sans arrosage, le sol sèche (régression : l'arrondi la faisait disparaître)
        jamais_arrosees = [hist for hist in historiques.values() if not any(m["vanne_ouverte"] for m in hist)]
        assert jamais_arrosees
        for hist in jamais_arrosees:
            assert hist[-1]["humidite_sol_pct"] < hist[0]["humidite_sol_pct"] or hist[0]["humidite_sol_pct"] >= 95

        # les vannes se referment après leur durée (régression : elles restaient ouvertes indéfiniment, +40 points d'humidité)
        for pid in historiques:                                             # chaque ouverture est bornée (une parcelle très
            for e in c.get(f"/parcelles/{pid}/historique").json():          # assoiffée peut être rouverte à la suite, mais
                assert e["minutes"] <= 120                                  # aucune vanne ne reste ouverte indéfiniment)
        assert all(max(m["humidite_sol_pct"] for m in hist) <= max(avant[i] + 25, 95.0) for i, hist in historiques.items()), \
            "régression : une vanne restée ouverte faisait gagner +40 points d'humidité"
        arrosees = [hist for hist in historiques.values() if any(m["vanne_ouverte"] for m in hist)]
        assert len(arrosees) >= 3                                           # le mode auto a arrosé (plage 5 h-9 h)
        assert any(any(a["vanne_ouverte"] and not b["vanne_ouverte"] for a, b in zip(hist, hist[1:])) for hist in arrosees)

        # un seul temps pour tout le système : l'historique des arrosages est daté en temps simulé
        pid = next(p["id"] for p in parcelles if any(m["vanne_ouverte"] for m in historiques[p["id"]]))
        dates = [a["date"] for a in c.get(f"/parcelles/{pid}/historique").json()]
        assert dates and all("2026-10-08T05" <= d < "2026-10-08T10" for d in dates)
        assert mp.maintenant() == sim.ETAT["horloge"] == datetime(2026, 10, 8, 10, 0)

        assert c.get("/meteo").json()["source"].startswith("simulation")
        assert c.post("/meteo/actualiser").status_code == 409               # météo réelle impossible pendant la simulation
        sim.ETAT["horloge"] = None                                          # redémarrage : reprise après la dernière mesure
        sim.avancer(Session)
        assert c.get(f"/parcelles/{parcelles[0]['id']}/mesures?limit=2").json()[-1]["date"] == "2026-10-08T10:00:00"
        etat = c.post("/simulation/pause").json()
        assert etat["active"] is False and etat["acceleration"] == 120
        figee = mp.maintenant()
        assert mp.maintenant() == figee                                     # en pause, le temps ne passe plus
        assert c.post("/simulation/reprendre").json()["active"] is True
    finally:
        meteo.METEO.update(sauve[0]); meteo.INFO.update(sauve[1]); sim._pluie.clear()


def test_simulation_desactivee_refuse_de_reprendre(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(sim, "SECONDES", 0.0)
    assert client[0].get("/simulation").json()["disponible"] is False
    assert client[0].post("/simulation/reprendre").status_code == 409
