"""
Simulation des capteurs intégrée au serveur.

Tant que le serveur tourne (et que la simulation n'est pas en pause), les mesures des parcelles évoluent seules :
météo simulée, évapotranspiration, pluie, eau apportée par les vannes ouvertes. Le mode automatique arrose selon
la décision du système et le tableau de bord suit les courbes.

Le temps passe plus vite que la réalité : un pas = SIMULATION_PAS_MIN minutes simulées toutes les SIMULATION_SECONDES
secondes réelles (10 min toutes les 5 s = 120 fois plus vite). SIMULATION_SECONDES=0 désactive la simulation :
à faire quand de vrais capteurs enverront les mesures (PUT /parcelles/{id}).
"""
import math
import os
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from .database import SessionLocal
from .engine.irrigation import STADES, et0_hargreaves
from .models import Plant
from .models_parcelles import Mesure, Parcelle, _horloge
from .routers import meteo
from .routers.parcelles import DEBIT_POMPE_LH, passe_auto

PAS_MIN = float(os.getenv("SIMULATION_PAS_MIN", "10"))
SECONDES = float(os.getenv("SIMULATION_SECONDES", "5"))
PROBA_PLUIE = float(os.getenv("SIMULATION_PROBA_PLUIE", "0.35"))
GAIN, EFF = 1.2, 0.9                 # % d'humidité gagnés par mm d'eau ; efficience du goutte-à-goutte
PERTE = {"Sableux": 1.15, "Limoneux": 1.0, "Argileux": 0.9}
CONSERVER = 1500                     # mesures gardées par parcelle (les plus anciennes sont effacées)

ETAT = {"actif": SECONDES > 0, "horloge": None, "pas": 0}
PANNES: dict[int, str] = {}          # pannes injectées pour tester les alertes : {id parcelle: "bloque" | "aberrant" | "vanne"}
_reel: dict[int, dict] = {}          # vraies valeurs d'une parcelle dont le capteur est en panne (le sol, lui, continue de vivre)
_pluie: list[float] = []             # pluie (mm) des pas à venir
rng = random.Random()


def actif() -> bool:
    return ETAT["actif"]


def _fuseau():
    try:
        return ZoneInfo(os.getenv("FERME_FUSEAU", "Africa/Kinshasa"))
    except Exception:
        return timezone(timedelta(hours=1))


def _heure_locale(h: datetime) -> float:
    """Heure locale de la ferme (0-24) pour une heure UTC simulée : sert aux plages d'arrosage et au cycle jour/nuit."""
    loc = h.replace(tzinfo=timezone.utc).astimezone(_fuseau())
    return loc.hour + loc.minute / 60


def _regler_horloge(h: datetime):
    ETAT["horloge"] = h
    if SECONDES > 0:
        _horloge["simulee"] = h          # tout le système lit maintenant() : l'heure simulée, figée pendant la pause


def initialiser(session_factory=None):
    """Au démarrage : le temps simulé reprend après la dernière mesure enregistrée (ou à l'heure réelle au 1er lancement)."""
    with (session_factory or SessionLocal)() as db:
        dernier = db.scalar(select(func.max(Mesure.at)))
    _regler_horloge(dernier + timedelta(minutes=PAS_MIN) if dernier else datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0))


def _pluie_du_jour() -> list[float]:
    n = int(1440 / PAS_MIN)
    jour = [0.0] * n
    if rng.random() < PROBA_PLUIE:
        debut = rng.randint(n // 3, int(n / 1.5))
        for k in range(rng.randint(int(60 / PAS_MIN), int(180 / PAS_MIN))):
            if debut + k < n:
                jour[debut + k] = rng.uniform(0.3, 1.2) * PAS_MIN / 10
    return jour


def _elaguer(db):
    for pid in list(db.scalars(select(Parcelle.id))):
        seuil = db.scalar(select(Mesure.id).where(Mesure.parcelle_id == pid).order_by(Mesure.id.desc()).offset(CONSERVER).limit(1))
        if seuil:
            db.execute(delete(Mesure).where(Mesure.parcelle_id == pid, Mesure.id <= seuil))
    db.commit()


def avancer(session_factory=None):
    """Un pas de simulation : météo, évolution de chaque parcelle, enregistrement, puis passe automatique."""
    with (session_factory or SessionLocal)() as db:
        if ETAT["horloge"] is None:
            db.close()
            initialiser(session_factory)
            return avancer(session_factory)
        h = ETAT["horloge"]
        _horloge["simulee"] = h
        heure = _heure_locale(h)
        regard = int(360 / PAS_MIN)
        while len(_pluie) < regard + 1:
            _pluie.extend(_pluie_du_jour())
        pluie_pas = _pluie.pop(0)
        prevision = sum(_pluie[:regard])
        s = math.sin(2 * math.pi * (heure - 9) / 24)
        t = 27 + 5 * s + rng.gauss(0, 0.4)
        rh = min(100.0, max(25.0, 72 - 20 * s + rng.gauss(0, 2)))
        meteo._appliquer({"temperature_air_c": round(t, 1), "humidite_air_pct": round(rh, 1),
                          "prevision_pluie_6h_mm": round(prevision, 1)}, "simulation (capteurs simulés)", False)
        et0 = et0_hargreaves(t, rh)
        for p in db.scalars(select(Parcelle)):
            pl = db.get(Plant, p.plant_id)
            m = dict(_reel.get(p.id) or p.mesures)          # état réel du sol (≠ valeur lue si le capteur est en panne)
            panne = PANNES.get(p.id)
            hum = m["humidite_sol_pct"] - getattr(pl, STADES[p.stade]) * et0 / (1440 / PAS_MIN) * GAIN * PERTE[p.type_sol] + pluie_pas
            # part du pas écoulé [h - PAS, h] pendant laquelle la vanne était ouverte : une ouverture de 8 min dans un pas de
            # 10 min apporte 80 % de l'eau (avant, elle était ignorée et le système rouvrait la vanne à chaque pas)
            ouverte = 0.0 if not p.vanne_fin else max(0.0, min(1.0, (p.vanne_fin - (h - timedelta(minutes=PAS_MIN))).total_seconds() / 60 / PAS_MIN))
            if ouverte > 0 and panne != "vanne":                      # panne « vanne » : elle est ouverte mais l'eau n'arrive pas
                litres = pl.debit_plant_lph * p.surface_m2 * pl.densite_plants_ha / 10000 * PAS_MIN / 60 * ouverte
                hum += litres / p.surface_m2 * GAIN * EFF
            # 3 décimales : l'évaporation d'un pas de 10 min (≈ 0,03 point) disparaîtrait avec un arrondi à 0,1
            m["humidite_sol_pct"] = round(min(95.0, max(5.0, hum)), 3)
            m["temperature_sol_c"] = round(m["temperature_sol_c"] + 0.12 * ((0.7 * t + 7) - m["temperature_sol_c"]), 3)
            for k in ("azote_N_mgkg", "phosphore_P_mgkg", "potassium_K_mgkg"):
                m[k] = round(m[k] * 0.9997, 3)
            if panne in ("bloque", "aberrant"):
                _reel[p.id] = dict(m)                                 # le sol évolue, mais le capteur ment
                m = dict(p.mesures) if panne == "bloque" else {**m, "humidite_sol_pct": 0.0}
            else:
                _reel.pop(p.id, None)
            p.mesures = m
            db.add(Mesure(parcelle_id=p.id, at=h, mesures=m, vanne_ouverte=ouverte > 0))
        db.commit()
        passe_auto(db, dict(meteo.METEO), DEBIT_POMPE_LH, heure)
        _regler_horloge(h + timedelta(minutes=PAS_MIN))
        ETAT["pas"] += 1
        if ETAT["pas"] % 60 == 0:
            _elaguer(db)
