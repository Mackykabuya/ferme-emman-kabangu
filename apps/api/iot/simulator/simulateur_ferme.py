#!/usr/bin/env python3
"""
Simulateur de la ferme entière (10 parcelles) - remplace les capteurs.

À chaque pas (30 minutes simulées) : fixe la météo (PUT /meteo), fait évoluer l'humidité, la température et
les nutriments de CHAQUE parcelle (évapotranspiration, pluie, eau apportée par les vannes ouvertes), puis met à jour
leurs mesures dans l'API (PUT /parcelles/{id}). À chaque pas, il déclenche une passe du mode automatique, qui
décide quelles vannes ouvrir en respectant la capacité de la pompe. Il ferme chaque vanne quand sa durée simulée est écoulée.

Prérequis : l'API tourne (uvicorn app.main:app --reload). Modèle physique volontairement simple.
  python iot/simulator/simulateur_ferme.py --jours 2
  python iot/simulator/simulateur_ferme.py --jours 3 --canicule --proba-pluie 0.1
  python iot/simulator/simulateur_ferme.py --jours 0 --delai 2      # en continu, pour suivre le tableau de bord en direct
"""
import argparse
import itertools
import math
import random
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

GAIN, EFF = 1.2, 0.9          # % d'humidité gagnés par mm d'eau ; efficience du goutte-à-goutte
PERTE = {"Sableux": 1.15, "Limoneux": 1.0, "Argileux": 0.9}
KC = {"Germination": "kc_germination", "Croissance végétative": "kc_vegetative",
      "Floraison": "kc_floraison", "Fructification/Maturation": "kc_fructification"}


def et0(t, rh):
    return 0.0023 * (t + 17.8) * math.sqrt(min(14.0, max(5.0, 14 - 0.08 * rh))) * 15.5


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--jours", type=int, default=2, help="durée simulée ; 0 = sans fin (Ctrl+C pour arrêter)")
    ap.add_argument("--pas-min", type=int, default=30)
    ap.add_argument("--proba-pluie", type=float, default=0.35)
    ap.add_argument("--canicule", action="store_true", help="+8 °C sur toute la période")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--delai", type=float, default=0, help="pause réelle (secondes) entre deux pas ; 2 pour suivre en direct")
    a = ap.parse_args()
    rng, c, par_jour = random.Random(a.seed), httpx.Client(base_url=a.api, timeout=20), 1440 // a.pas_min
    try:
        plantes = {p["id"]: p for p in c.get("/plants").json()}
    except httpx.HTTPError as e:
        sys.exit(f"API injoignable ({a.api}). Lancez d'abord : uvicorn app.main:app --reload\n{e}")

    def pluie_du_jour():                                          # mm par pas pour une journée
        jour = [0.0] * par_jour
        if rng.random() < a.proba_pluie:
            d = rng.randint(par_jour // 3, int(par_jour / 1.5))
            for k in range(rng.randint(2, 6)):
                if d + k < par_jour:
                    jour[d + k] = rng.uniform(0.8, 3.0)
        return jour

    pluie = []
    arret = []
    signal.signal(signal.SIGINT, lambda *_: arret.append(1))      # Ctrl+C : on termine proprement le pas en cours
    debut = datetime.now(timezone.utc).replace(tzinfo=None, minute=0, second=0, microsecond=0)   # horloge simulée

    ouvre, litres_total, ouvertures = {}, 0.0, 0                  # id -> (minute d'ouverture, durée prévue)
    print(f"{'Jour':<5}{'Heure':<7}{'T°C':>5}{'Pluie':>6}{'Vannes':>7}{'Hum.moy':>9}  Passe automatique")
    print("-" * 100)
    for pas in itertools.count():
        if arret or (a.jours and pas >= a.jours * par_jour):
            break
        while len(pluie) < pas + par_jour:
            pluie.extend(pluie_du_jour())
        minute = pas * a.pas_min
        heure = (minute % 1440) / 60
        t = 27 + 5 * math.sin(2 * math.pi * (heure - 9) / 24) + rng.gauss(0, 0.4) + (8 if a.canicule else 0)
        rh = min(100.0, max(25.0, 72 - 20 * math.sin(2 * math.pi * (heure - 9) / 24) + rng.gauss(0, 2) - (10 if a.canicule else 0)))
        prevision = sum(pluie[pas:pas + 360 // a.pas_min])
        c.put("/meteo", json={"temperature_air_c": round(t, 1), "humidite_air_pct": round(rh, 1),
                              "prevision_pluie_6h_mm": round(prevision, 1)}).raise_for_status()
        ouvertes, hums = 0, []
        for p in c.get("/parcelles").json():
            pl, m = plantes[p["plant_id"]], dict(p["mesures"])
            h = m["humidite_sol_pct"] - pl[KC[p["stade"]]] * et0(t, rh) / par_jour * GAIN * PERTE[p["type_sol"]] + pluie[pas]
            if p["vanne_ouverte"]:
                ouvertes += 1
                if p["id"] not in ouvre:
                    hist = c.get(f"/parcelles/{p['id']}/historique").json()
                    ouvre[p["id"]] = (minute, hist[0]["minutes"] if hist else 30)
                    ouvertures += 1
                litres = pl["debit_plant_lph"] * p["surface_m2"] * pl["densite_plants_ha"] / 10000 * a.pas_min / 60
                litres_total += litres
                h += litres / p["surface_m2"] * GAIN * EFF
            m["humidite_sol_pct"] = round(min(95.0, max(5.0, h)), 1)
            m["temperature_sol_c"] = round(m["temperature_sol_c"] + 0.3 * ((0.7 * t + 7) - m["temperature_sol_c"]), 1)
            for k in ("azote_N_mgkg", "phosphore_P_mgkg", "potassium_K_mgkg"):
                m[k] = round(m[k] * 0.999, 1)
            c.put(f"/parcelles/{p['id']}", json={"mesures": m, "horodatage": (debut + timedelta(minutes=minute)).isoformat()}).raise_for_status()
            hums.append(m["humidite_sol_pct"])
            if p["id"] in ouvre and minute - ouvre[p["id"]][0] >= ouvre[p["id"]][1]:     # durée écoulée : on ferme
                c.post(f"/parcelles/{p['id']}/vanne", json={"action": "fermer"})
                del ouvre[p["id"]]
        r = c.post("/parcelles/appliquer-auto", params={"heure": heure}).json()      # comme le planificateur de l'API : une passe à chaque pas
        texte = ""
        if r["vannes_ouvertes"] or r["en_attente_de_pompe"]:
            texte = f"ouvre {', '.join(n[-2:] for n in r['vannes_ouvertes']) or 'aucune'}" + (f" | attend la pompe : {', '.join(n[-2:] for n in r['en_attente_de_pompe'])}" if r["en_attente_de_pompe"] else "")
        elif r["hors_plage_horaire"] and minute % 360 == 0:
            texte = f"{len(r['hors_plage_horaire'])} parcelle(s) attendent la plage d'arrosage ({r['plages']})"
        print(f"J{minute // 1440 + 1:<4}{int(heure):02d}h{int(heure % 1 * 60):02d} {t:>5.1f}{pluie[pas]:>6.1f}{ouvertes:>7}{sum(hums) / len(hums):>8.1f}%  {texte}")
        time.sleep(a.delai)

    print("-" * 100)
    print(f"Bilan : {ouvertures} ouvertures de vanne, {litres_total:,.0f} L apportés, {sum(pluie[:pas]):.0f} mm de pluie.".replace(",", " "))
    print("\nÉtat final des parcelles :")
    for p in c.get("/parcelles/apercu").json():
        g = p["decision"]["etape_1_diagnostic"]
        print(f"  {p['nom']:<12}{p['plante']:<16}{g['etat_sante_libelle'][:34]:<36}sol {p['mesures']['humidite_sol_pct']:>5.1f} %")


if __name__ == "__main__":
    main()
