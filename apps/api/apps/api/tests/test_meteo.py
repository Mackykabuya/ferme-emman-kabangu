import httpx
import pytest

from app.routers import meteo as m
from tests.test_parcelles import ferme  # noqa: F401
from tests.test_plants import client  # noqa: F401

OPEN_METEO = {  # même forme que la réponse d'Open-Meteo (heures locales, format ISO sans fuseau)
    "current": {"time": "2026-10-08T14:15", "temperature_2m": 31.4, "relative_humidity_2m": 62},
    "hourly": {"time": [f"2026-10-08T{h:02d}:00" for h in range(24)] + [f"2026-10-09T{h:02d}:00" for h in range(24)],
               "precipitation": [0.0] * 14 + [0.4, 1.0, None, 0.0, 2.0, 0.6, 0.4, 9.0] + [0.0] * 26},
}


@pytest.fixture(autouse=True)
def meteo_propre():
    sauve = (dict(m.METEO), dict(m.INFO))
    yield
    m.METEO.update(sauve[0]); m.INFO.update(sauve[1])


def test_analyse_de_la_reponse_open_meteo():
    r = m.analyser_open_meteo(OPEN_METEO)
    assert r == {"temperature_air_c": 31.4, "humidite_air_pct": 62.0, "prevision_pluie_6h_mm": 4.0}   # 15h à 20h, pas l'heure en cours ni 21h


def test_actualiser_meteo_reelle_et_erreur_reseau(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(m, "recuperer", lambda: m.analyser_open_meteo(OPEN_METEO))
    r = client[0].post("/meteo/actualiser")
    assert r.status_code == 200 and r.json()["source"].startswith("Open-Meteo") and r.json()["prevision_pluie_6h_mm"] == 4.0
    assert "5 h-9 h" in r.json()["plages"] and client[0].get("/meteo").json()["temperature_air_c"] == 31.4

    def panne():
        raise httpx.ConnectError("hors ligne")
    monkeypatch.setattr(m, "recuperer", panne)
    assert client[0].post("/meteo/actualiser").status_code == 502


def test_une_saisie_manuelle_suspend_la_meteo_reelle(client, monkeypatch):  # noqa: F811
    client[0].put("/meteo", json={"temperature_air_c": 33, "humidite_air_pct": 40, "prevision_pluie_6h_mm": 0})
    assert client[0].get("/meteo").json()["source"] == "saisie manuelle"
    monkeypatch.setattr(m, "recuperer", lambda: pytest.fail("la météo réelle ne doit pas écraser une saisie manuelle"))
    m.actualiser_auto()                                             # ne fait rien : saisie manuelle récente
    m.INFO["manuel_jusqua"] = m.maintenant() - m.timedelta(minutes=1)
    monkeypatch.setattr(m, "recuperer", lambda: {"temperature_air_c": 25.0, "humidite_air_pct": 80.0, "prevision_pluie_6h_mm": 0.0})
    m.actualiser_auto()                                             # saisie expirée : la météo réelle reprend
    assert m.METEO["temperature_air_c"] == 25.0 and m.INFO["source"].startswith("Open-Meteo")


def test_plages_horaires_d_arrosage(ferme):  # noqa: F811
    nuit = ferme.post("/parcelles/appliquer-auto?debit_pompe=1e12&heure=12").json()
    assert nuit["vannes_ouvertes"] == [] and len(nuit["hors_plage_horaire"]) >= 5 and "17 h-20 h" in nuit["plages"]
    matin = ferme.post("/parcelles/appliquer-auto?debit_pompe=1e12&heure=6").json()
    assert matin["vannes_ouvertes"] and matin["hors_plage_horaire"] == []
    assert ferme.post("/parcelles/appliquer-auto?heure=24").status_code == 422


def test_un_sol_critique_est_arrose_meme_hors_plage(ferme):  # noqa: F811
    a2 = next(p for p in ferme.get("/parcelles").json() if p["nom"] == "Parcelle A2")        # manioc : idéal 40 à 62 %
    ferme.put(f"/parcelles/{a2['id']}", json={"mesures": {"humidite_sol_pct": 20}})
    r = ferme.post("/parcelles/appliquer-auto?debit_pompe=1e12&heure=12").json()
    assert r["vannes_ouvertes"] == ["Parcelle A2"] and "Parcelle A2" not in r["hors_plage_horaire"]
