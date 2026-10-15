"""Météo du moment : réelle (Open-Meteo, gratuit, sans clé) ou saisie à la main / par le simulateur."""
import os
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import exiger

router = APIRouter(prefix="/meteo", tags=["Météo"])

# Position de la ferme. Valeurs provisoires (Kinshasa) : à remplacer par les vraies coordonnées de la ferme.
LATITUDE = float(os.getenv("FERME_LATITUDE", "-4.32"))
LONGITUDE = float(os.getenv("FERME_LONGITUDE", "15.31"))
SAISIE_MANUELLE_HEURES = 2      # une saisie manuelle (ou le simulateur) suspend la météo réelle pendant ce temps

METEO = {"temperature_air_c": 30.0, "humidite_air_pct": 55.0, "prevision_pluie_6h_mm": 0.0}
INFO = {"source": "valeurs par défaut", "mis_a_jour": None, "manuel_jusqua": None}


class Meteo(BaseModel):
    temperature_air_c: float = Field(ge=-5, le=55)
    humidite_air_pct: float = Field(ge=0, le=100)
    prevision_pluie_6h_mm: float = Field(ge=0, le=300)


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def analyser_open_meteo(d: dict) -> dict:
    """Température et humidité actuelles + pluie cumulée (mm) sur les 6 heures suivantes.
    Open-Meteo : la valeur horaire de 15:00 est la pluie tombée entre 14 h et 15 h ; à 14 h 15, les 6 prochaines
    heures correspondent donc aux valeurs de 15:00 à 20:00."""
    cur, h = d["current"], d["hourly"]
    i = max((k for k, t in enumerate(h["time"]) if t <= cur["time"]), default=0)     # heure en cours (même format de date)
    pluie = sum(x or 0 for x in h["precipitation"][i + 1:i + 7])
    return {"temperature_air_c": float(cur["temperature_2m"]), "humidite_air_pct": float(cur["relative_humidity_2m"]),
            "prevision_pluie_6h_mm": round(pluie, 1)}


def recuperer() -> dict:
    r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=10, params={
        "latitude": LATITUDE, "longitude": LONGITUDE, "current": "temperature_2m,relative_humidity_2m",
        "hourly": "precipitation", "forecast_days": 2, "timezone": "auto"})
    r.raise_for_status()
    return analyser_open_meteo(r.json())


def _appliquer(m: dict, source: str, manuel: bool):
    METEO.update(m)
    INFO.update(source=source, mis_a_jour=maintenant().isoformat(timespec="seconds"),
                manuel_jusqua=maintenant() + timedelta(hours=SAISIE_MANUELLE_HEURES) if manuel else None)


def actualiser_auto():
    """Appelée périodiquement par main.py : ne touche à rien pendant une saisie manuelle / une simulation."""
    from .. import simulation
    if simulation.actif() or (INFO["manuel_jusqua"] and INFO["manuel_jusqua"] > maintenant()):
        return
    _appliquer(recuperer(), "Open-Meteo (météo réelle)", False)


def _etat() -> dict:
    from .parcelles import texte_plages
    return {**METEO, "source": INFO["source"], "mis_a_jour": INFO["mis_a_jour"], "plages": texte_plages(),
            "position": {"latitude": LATITUDE, "longitude": LONGITUDE}}


@router.get("")
def lire():
    return _etat()


@router.put("", dependencies=[Depends(exiger("operateur"))])
def regler(m: Meteo):
    """Fixe la météo à la main. La météo réelle est suspendue 2 heures (le temps d'un test ou d'une simulation)."""
    _appliquer(m.model_dump(), "saisie manuelle", True)
    return _etat()


@router.post("/actualiser", dependencies=[Depends(exiger("operateur"))])
def actualiser():
    """Récupère la météo réelle maintenant (Open-Meteo)."""
    from .. import simulation
    if simulation.actif():
        raise HTTPException(409, "La simulation est en cours : mettez-la en pause pour utiliser la météo réelle.")
    try:
        _appliquer(recuperer(), "Open-Meteo (météo réelle)", False)
    except (httpx.HTTPError, KeyError, ValueError):
        raise HTTPException(502, "Impossible d'obtenir la météo réelle (Open-Meteo). Vérifiez la connexion Internet.")
    return _etat()
