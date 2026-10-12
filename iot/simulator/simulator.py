#!/usr/bin/env python3
"""
Simulateur de parcelle - Ferme Emman Kabangu
============================================
Remplace les capteurs physiques : simule la météo, l'humidité du sol, la pluie et les analyses de sol.
À 6 h et à 17 h, il envoie les mesures à l'API (POST /decision/parcelle) qui fait d'abord le DIAGNOSTIC
du sol, puis calcule l'ARROSAGE corrigé selon ce diagnostic. La vanne virtuelle s'ouvre ou reste fermée,
et un bilan d'eau est affiché à la fin.

Prérequis : l'API doit tourner (uvicorn app.main:app) dans un autre terminal.
Modèle physique volontairement simple : il sert à tester la chaîne complète, pas à prédire la réalité.

Scénarios (--scenario) :
  sain            sol équilibré, météo normale
  carence_azote   le sol manque d'azote (le diagnostic doit le détecter)
  canicule        températures +8 °C : sol trop chaud, l'arrosage doit augmenter

Exemples :
  python iot/simulator/simulator.py --plante Piment --stade Floraison --jours 5
  python iot/simulator/simulator.py --plante Tomate --scenario canicule --jours 4
  python iot/simulator/simulator.py --plante Maïs --scenario carence_azote --sol Sableux
"""
import argparse
import math
import random
import sys
from collections import Counter

import httpx

PAS_MIN = 30                       # un pas de simulation = 30 minutes
PAS_PAR_JOUR = 24 * 60 // PAS_MIN
HEURES_DECISION = (6, 17)          # moments où le système décide d'arroser
PERTE_SOL = {"Sableux": 1.15, "Limoneux": 1.0, "Argileux": 0.9}
GAIN_PCT_PAR_MM = 1.2              # % d'humidité du sol gagnés par mm d'eau apportée
EFFICIENCE = 0.90


def et0(t, rh):
    amplitude = min(14.0, max(5.0, 14 - 0.08 * rh))
    return 0.0023 * (t + 17.8) * math.sqrt(amplitude) * 15.5


def meteo(heure, rng, scenario):
    t = 27 + 5 * math.sin(2 * math.pi * (heure - 9) / 24) + rng.gauss(0, 0.4)
    rh = 72 - 20 * math.sin(2 * math.pi * (heure - 9) / 24) + rng.gauss(0, 2)
    if scenario == "canicule":
        t, rh = t + 8, rh - 10
    return t, min(100.0, max(25.0, rh))


def planifier_pluie(jours, rng, proba):
    """Retourne un tableau mm de pluie par pas de 30 min."""
    pluie = [0.0] * (jours * PAS_PAR_JOUR)
    for j in range(jours):
        if rng.random() < proba:
            debut = j * PAS_PAR_JOUR + rng.randint(10, 40)
            for k in range(rng.randint(2, 6)):
                if debut + k < len(pluie):
                    pluie[debut + k] = rng.uniform(0.8, 3.0)
    return pluie


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--plante", default="Piment")
    ap.add_argument("--stade", default="Floraison",
                    choices=["Germination", "Croissance végétative", "Floraison", "Fructification/Maturation"])
    ap.add_argument("--sol", default="Limoneux", choices=list(PERTE_SOL))
    ap.add_argument("--scenario", default="sain", choices=["sain", "carence_azote", "canicule"])
    ap.add_argument("--surface", type=float, default=1000, help="surface de la parcelle (m²)")
    ap.add_argument("--jours", type=int, default=5)
    ap.add_argument("--proba-pluie", type=float, default=0.3, help="probabilité de pluie par jour")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    try:
        plantes = httpx.get(f"{a.api}/plants", timeout=10).json()
    except httpx.HTTPError as e:
        sys.exit(f"API injoignable ({a.api}). Lancez d'abord : uvicorn app.main:app\n{e}")
    plante = next((p for p in plantes if p["nom"].lower() == a.plante.lower()), None)
    if not plante:
        sys.exit(f"Plante « {a.plante} » absente. Disponibles : {', '.join(p['nom'] for p in plantes)}")

    kc = {"Germination": plante["kc_germination"], "Croissance végétative": plante["kc_vegetative"],
          "Floraison": plante["kc_floraison"], "Fructification/Maturation": plante["kc_fructification"]}[a.stade]
    surface_par_plant = 10000 / plante["densite_plants_ha"]
    nb_plants = a.surface * plante["densite_plants_ha"] / 10000
    milieu = lambda lo, hi: (plante[lo] + plante[hi]) / 2
    humidite_sol = milieu("humidite_sol_min", "humidite_sol_max")

    # Analyses de sol simulées : équilibrées, sauf si le scénario en décide autrement
    ph, azote = milieu("ph_min", "ph_max"), milieu("n_min", "n_max")
    phosphore, potassium, ec = milieu("p_min", "p_max"), milieu("k_min", "k_max"), 0.5 * plante["ec_max_dsm"]
    if a.scenario == "carence_azote":
        azote *= 0.4

    print(f"\nParcelle : {a.surface:.0f} m² de {plante['nom']} ({a.stade}), sol {a.sol.lower()}, "
          f"~{nb_plants:.0f} plants - scénario « {a.scenario} » - humidité idéale du sol "
          f"{plante['humidite_sol_min']:.0f}-{plante['humidite_sol_max']:.0f} %\n")
    print(f"{'Jour':<5}{'Heure':<7}{'T°C':>5}{'HR%':>5}{'Sol%':>6}{'Pluie6h':>8}  {'Diagnostic':<31}Décision")
    print("-" * 118)

    pluie = planifier_pluie(a.jours, rng, a.proba_pluie)
    litres_utilises = litres_reference = pluie_totale = 0.0
    irrigations = reports = 0
    diagnostics = Counter()

    for pas in range(a.jours * PAS_PAR_JOUR):
        jour, h = divmod(pas, PAS_PAR_JOUR)
        heure = h * PAS_MIN / 60
        t, rh = meteo(heure, rng, a.scenario)
        etc_mm_pas = kc * et0(t, rh) / PAS_PAR_JOUR

        # Pertes (évapotranspiration) et apports de pluie
        humidite_sol -= etc_mm_pas * GAIN_PCT_PAR_MM * PERTE_SOL[a.sol]
        humidite_sol += pluie[pas]
        pluie_totale += pluie[pas]
        humidite_sol = max(5.0, min(90.0, humidite_sol))
        # Référence : irrigation systématique à 100 % de l'ETc, sans tenir compte de la pluie ni du sol
        litres_reference += etc_mm_pas * surface_par_plant * nb_plants / EFFICIENCE

        if abs(heure - round(heure)) < 1e-9 and int(round(heure)) in HEURES_DECISION:
            prevision = sum(pluie[pas:pas + 12]) * rng.uniform(0.85, 1.15)   # prévision 6 h, imparfaite
            r = httpx.post(f"{a.api}/decision/parcelle", timeout=10, json={
                "plant_id": plante["id"], "stade": a.stade, "type_sol": a.sol, "surface_parcelle_m2": a.surface,
                "ph": round(ph, 2), "humidite_sol_pct": round(humidite_sol, 1),
                "temperature_sol_c": round(0.7 * t + 7, 1), "azote_N_mgkg": round(azote, 1),
                "phosphore_P_mgkg": round(phosphore, 1), "potassium_K_mgkg": round(potassium, 1),
                "conductivite_ec_dsm": round(ec, 2), "temperature_air_c": round(t, 1),
                "humidite_air_pct": round(rh, 1), "prevision_pluie_6h_mm": round(prevision, 1)})
            r.raise_for_status()
            d = r.json()
            diag, irr = d["etape_1_diagnostic"], d["etape_2_irrigation"]
            diagnostics[diag["etat_sante_libelle"]] += 1
            if irr["vanne_ouverte"]:
                litres = irr["besoin_L_parcelle_jour"] * 0.5     # 50 % du volume journalier à chaque passage
                mm_effectifs = litres / (surface_par_plant * nb_plants) * EFFICIENCE
                humidite_sol = min(90.0, humidite_sol + mm_effectifs * GAIN_PCT_PAR_MM)
                litres_utilises += litres
                irrigations += 1
                texte = f"VANNE OUVERTE {irr['duree_min'] // 2:>3} min - {litres:>7.0f} L"
            else:
                reports += irr["code_decision"] == "pluie_forte"
                texte = "vanne fermée (" + {"pluie_forte": "grosse pluie annoncée",
                                           "sol_humide": "sol assez humide"}.get(irr["code_decision"], irr["code_decision"]) + ")"
            print(f"J{jour + 1:<4}{int(heure):02d}h00 {t:>5.1f}{rh:>5.0f}{humidite_sol:>6.1f}{prevision:>8.1f}  "
                  f"{diag['etat_sante_libelle'][:30]:<31}{texte}")
            derniere = d

    economie = 100 * (1 - litres_utilises / litres_reference) if litres_reference else 0
    print("-" * 118)
    print(f"Bilan sur {a.jours} jours : {irrigations} arrosages, {reports} report(s) pour pluie, "
          f"{pluie_totale:.0f} mm de pluie")
    print(f"Eau utilisée : {litres_utilises:,.0f} L | arrosage systématique équivalent : "
          f"{litres_reference:,.0f} L | économie : {economie:.0f} %".replace(",", " "))
    print("Diagnostics posés : " + ", ".join(f"{k} ({v})" for k, v in diagnostics.most_common()))
    print(f"\nExemple de message pour l'agriculteur (dernière décision) :\n{derniere['resume_agriculteur']}\n")


if __name__ == "__main__":
    main()
