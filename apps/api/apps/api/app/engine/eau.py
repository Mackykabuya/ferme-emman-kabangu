"""
Suivi de l'eau : litres réellement envoyés aux parcelles, comparés à un arrosage « classique ».

Arrosage classique = ce que ferait un exploitant sans capteurs : chaque jour, la même quantité, quels que soient la pluie
et l'état du sol, calculée sur une évapotranspiration de référence fixe (ET0_CLASSIQUE_MM_J, 5 mm/jour en climat chaud).
    litres/jour = Kc(stade) × ET0 classique × surface / efficience du goutte-à-goutte
C'est une base de comparaison simple et assumée, pas une mesure : changez ET0_CLASSIQUE_MM_J pour refléter vos habitudes.
Une économie n'est un bon signe que si les plantes vont bien (voir diagnostics et alertes) : arroser moins ne suffit pas.
"""
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .irrigation import EFFICIENCE

ET0_CLASSIQUE_MM_J = float(os.getenv("ET0_CLASSIQUE_MM_J", "5"))


def fuseau():
    try:
        return ZoneInfo(os.getenv("FERME_FUSEAU", "Africa/Kinshasa"))
    except Exception:
        return timezone(timedelta(hours=1))


def litres_classiques_jour(kc: float, surface_m2: float) -> float:
    return kc * ET0_CLASSIQUE_MM_J * surface_m2 / EFFICIENCE


def _locale(h: datetime, tz) -> datetime:
    return h.replace(tzinfo=timezone.utc).astimezone(tz)


def _tranches(a: datetime, b: datetime, tz):
    """Découpe [a, b] (UTC naïf) par jour local : (date locale, durée en heures)."""
    cur = _locale(a, tz)
    fin = _locale(b, tz)
    while cur < fin:
        minuit = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        suite = min(minuit, fin)
        yield cur.date(), (suite - cur).total_seconds() / 3600
        cur = suite


def _evenements_effectifs(arrosages: list[dict], debut: datetime, fin: datetime):
    """Pour chaque ouverture : (parcelle, début, fin réelle, litres réels). Une vanne fermée plus tôt (ou une période
    qui se termine avant la fin prévue) n'est comptée que pour le temps réellement écoulé."""
    par_parcelle: dict[int, list[dict]] = {}
    for a in sorted(arrosages, key=lambda x: x["at"]):
        par_parcelle.setdefault(a["parcelle_id"], []).append(a)
    for pid, evts in par_parcelle.items():
        for i, a in enumerate(evts):
            if a["action"] != "ouvrir" or a["minutes"] <= 0:
                continue
            prevue = a["at"] + timedelta(minutes=a["minutes"])
            fin_reelle = min(prevue, fin, evts[i + 1]["at"] if i + 1 < len(evts) else prevue)
            if fin_reelle <= a["at"]:
                continue
            part = (fin_reelle - a["at"]).total_seconds() / 60 / a["minutes"]
            yield pid, a["at"], fin_reelle, a["litres"] * part


def bilan(parcelles: list[dict], arrosages: list[dict], debut: datetime, fin: datetime) -> dict:
    """parcelles : {id, nom, surface_m2, kc}. arrosages : {parcelle_id, action, minutes, litres, at}. Dates UTC naïves."""
    tz = fuseau()
    jours = max(0.0, (fin - debut).total_seconds() / 86400)
    par = {p["id"]: {"id": p["id"], "nom": p["nom"], "reels": 0.0,
                     "classiques": litres_classiques_jour(p["kc"], p["surface_m2"]) * jours} for p in parcelles}
    jour: dict = {}

    def ligne(d):
        return jour.setdefault(d, {"date": d.isoformat(), "reels": 0.0, "classiques": 0.0})

    base_ferme = sum(litres_classiques_jour(p["kc"], p["surface_m2"]) for p in parcelles)
    for d, h in _tranches(debut, fin, tz):
        ligne(d)["classiques"] += base_ferme * h / 24
    for pid, a0, b0, litres in _evenements_effectifs(arrosages, debut, fin):
        if pid not in par:
            continue
        a, b = max(a0, debut), min(b0, fin)
        if b <= a:
            continue
        litres *= (b - a) / (b0 - a0)          # seule la part de l'ouverture située dans la période est comptée
        total_h = (b - a).total_seconds() / 3600
        par[pid]["reels"] += litres
        for d, h in _tranches(a, b, tz):       # répartis au prorata du temps passé dans chaque jour local
            ligne(d)["reels"] += litres * h / total_h
    return _finaliser(par, jour, jours, debut, fin)


def _finaliser(par, jour, jours, debut, fin):
    def conclu(reels, classiques):
        eco = classiques - reels
        return {"reels": round(reels), "classiques": round(classiques), "economie": round(eco),
                "economie_pct": round(100 * eco / classiques) if classiques > 0 else None}

    lignes = sorted(par.values(), key=lambda x: x["nom"])
    tot_r, tot_c = sum(x["reels"] for x in lignes), sum(x["classiques"] for x in lignes)
    return {"debut": debut.isoformat(), "fin": fin.isoformat(), "jours": round(jours, 2), "comparaison_fiable": jours >= 1,
            "ferme": conclu(tot_r, tot_c),
            "parcelles": [{"id": x["id"], "nom": x["nom"], **conclu(x["reels"], x["classiques"])} for x in lignes],
            "par_jour": [{"date": j["date"], "reels": round(j["reels"]), "classiques": round(j["classiques"])}
                         for _, j in sorted(jour.items())],
            "methode": (f"Arrosage classique = chaque jour la même quantité, sans tenir compte de la pluie ni du sol "
                        f"(évapotranspiration fixée à {ET0_CLASSIQUE_MM_J:g} mm/jour × coefficient de la culture).")}
