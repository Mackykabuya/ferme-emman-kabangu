from tests.test_parcelles import ferme  # noqa: F401
from tests.test_plants import client  # noqa: F401


def test_historique_des_mesures_pour_les_graphiques(ferme):  # noqa: F811
    pid = ferme.get("/parcelles").json()[0]["id"]
    assert ferme.get(f"/parcelles/{pid}/mesures").json() == []
    for h, hum in [("2026-10-08T06:00:00", 50.0), ("2026-10-08T06:30:00", 52.5), ("2026-10-08T07:00:00", 55.0)]:
        assert ferme.put(f"/parcelles/{pid}", json={"mesures": {"humidite_sol_pct": hum}, "horodatage": h}).status_code == 200
    ferme.post(f"/parcelles/{pid}/vanne", json={"action": "ouvrir", "duree_min": 10})
    ferme.put(f"/parcelles/{pid}", json={"mesures": {"humidite_sol_pct": 57.0}, "horodatage": "2026-10-08T07:30:00"})
    h = ferme.get(f"/parcelles/{pid}/mesures").json()
    assert [m["humidite_sol_pct"] for m in h] == [50.0, 52.5, 55.0, 57.0]                  # chronologique
    assert [m["vanne_ouverte"] for m in h] == [False, False, False, True] and h[0]["date"] == "2026-10-08T06:00:00"
    assert "azote_N_mgkg" in h[0]                                                           # toutes les mesures sont conservées
    assert len(ferme.get(f"/parcelles/{pid}/mesures?limit=2").json()) == 2
    ferme.put(f"/parcelles/{pid}", json={"nom": "Renommée"})                                # sans mesures : pas de nouveau point
    assert len(ferme.get(f"/parcelles/{pid}/mesures").json()) == 4
    assert ferme.delete(f"/parcelles/{pid}").status_code == 204 and ferme.get(f"/parcelles/{pid}/mesures").status_code == 404
