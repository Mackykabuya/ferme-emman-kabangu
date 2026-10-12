#!/usr/bin/env python3
"""
Ferme Emman Kabangu - Génération de datasets synthétiques
=========================================================
Produit :
  - dataset_pedologique.csv   : diagnostic pédologique (classification + recommandation)
  - dataset_irrigation.csv    : besoin en eau modulé (régression + décision vanne)
  - catalogue_plantes.json    : paramètres agronomiques (graine pour la table `plants` en base)

Principe : le catalogue ci-dessous est la SOURCE UNIQUE de vérité agronomique.
Ajouter une plante = ajouter une entrée au catalogue (ou une ligne en base via l'API) ;
les deux générateurs s'adaptent automatiquement.

Les valeurs sont des ordres de grandeur agronomiques (FAO-56 pour les Kc) destinés à
amorcer le projet. Elles doivent être validées par un agronome puis remplacées
progressivement par des mesures réelles de la ferme.

Les recommandations et le calcul d'irrigation viennent de apps/api/app/engine (même code que l'API).
Usage : python generate_datasets.py --n-pedo 6000 --n-irrig 10000 --seed 42 --out ./data
"""
import argparse
import json
import math
from pathlib import Path

import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd

# Le moteur de l'API est la source unique de vérité : le dataset d'irrigation est produit avec lui.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.engine.conseils import texte_complet, conseils_diagnostic  # noqa: E402
from app.engine.irrigation import estimer_irrigation  # noqa: E402

# --------------------------------------------------------------------------------------
# 1. CATALOGUE DES PLANTES
# kc = [Germination, Croissance végétative, Floraison, Fructification/Maturation]
# n/p/k = plage optimale en mg/kg ; humidite_sol = plage optimale (%) ; temp_opt en °C
# densite = plants/ha ; debit_plant_lph = débit d'irrigation par plant (L/h)
# tol_hydrique : 1 = très sensible à la sécheresse ... 5 = très tolérante
# --------------------------------------------------------------------------------------
LEG, CER, FRU = "Légumes & Maraîchage", "Céréales & Tubercules", "Fruits / Autres"

CATALOGUE = {
    "Piment": dict(categorie=LEG, varietes=["Pili-pili local", "Habanero", "Cayenne"],
                   kc=[0.60, 0.85, 1.05, 0.90], ph=(5.8, 6.8), n=(40, 80), p=(20, 40), k=(120, 200),
                   ec_max=1.5, humidite_sol=(55, 75), temp_opt=(22, 30), densite=20000,
                   debit_plant_lph=4, tol_hydrique=2),
    "Tomate": dict(categorie=LEG, varietes=["Roma", "Money Maker", "Marmande", "Heinz"],
                   kc=[0.60, 0.90, 1.15, 0.80], ph=(6.0, 6.8), n=(50, 90), p=(25, 50), k=(150, 250),
                   ec_max=2.5, humidite_sol=(60, 80), temp_opt=(20, 28), densite=25000,
                   debit_plant_lph=4, tol_hydrique=2),
    "Poivron": dict(categorie=LEG, varietes=["California Wonder", "Yolo Wonder"],
                    kc=[0.60, 0.85, 1.05, 0.90], ph=(6.0, 6.8), n=(45, 85), p=(25, 45), k=(140, 220),
                    ec_max=1.5, humidite_sol=(60, 78), temp_opt=(21, 29), densite=30000,
                    debit_plant_lph=4, tol_hydrique=2),
    "Gombo": dict(categorie=LEG, varietes=["Clemson Spineless", "Locale Kinshasa"],
                  kc=[0.50, 0.80, 1.05, 0.85], ph=(6.0, 7.0), n=(35, 70), p=(20, 40), k=(100, 180),
                  ec_max=2.0, humidite_sol=(50, 70), temp_opt=(24, 33), densite=40000,
                  debit_plant_lph=3, tol_hydrique=4),
    "Aubergine": dict(categorie=LEG, varietes=["Black Beauty", "Longue violette"],
                      kc=[0.60, 0.90, 1.10, 0.90], ph=(5.8, 6.8), n=(45, 85), p=(25, 45), k=(130, 220),
                      ec_max=1.8, humidite_sol=(58, 78), temp_opt=(22, 30), densite=20000,
                      debit_plant_lph=4, tol_hydrique=3),
    "Amarante (Loso)": dict(categorie=LEG, varietes=["Loso vert", "Loso rouge"],
                            kc=[0.50, 0.80, 1.00, 0.85], ph=(5.8, 7.0), n=(60, 110), p=(20, 40), k=(100, 180),
                            ec_max=2.0, humidite_sol=(55, 75), temp_opt=(22, 32), densite=500000,
                            debit_plant_lph=0.5, tol_hydrique=3),
    "Chou": dict(categorie=LEG, varietes=["Gloria F1", "Copenhagen Market"],
                 kc=[0.70, 0.90, 1.05, 0.95], ph=(6.0, 7.0), n=(60, 110), p=(25, 45), k=(150, 240),
                 ec_max=1.8, humidite_sol=(65, 82), temp_opt=(16, 25), densite=40000,
                 debit_plant_lph=4, tol_hydrique=2),
    "Maïs": dict(categorie=CER, varietes=["Samaru (OPV)", "Hybride SC"],
                 kc=[0.40, 0.80, 1.20, 0.60], ph=(5.8, 7.0), n=(50, 100), p=(20, 40), k=(110, 190),
                 ec_max=1.7, humidite_sol=(50, 70), temp_opt=(20, 32), densite=55000,
                 debit_plant_lph=4, tol_hydrique=3),
    "Manioc": dict(categorie=CER, varietes=["Variété améliorée anti-mosaïque", "Locale douce"],
                   kc=[0.30, 0.70, 1.10, 0.50], ph=(5.0, 6.5), n=(30, 60), p=(10, 30), k=(80, 150),
                   ec_max=1.5, humidite_sol=(40, 62), temp_opt=(23, 32), densite=10000,
                   debit_plant_lph=6, tol_hydrique=5),
    "Patate douce": dict(categorie=CER, varietes=["Chair orange (OFSP)", "Chair blanche"],
                         kc=[0.50, 0.75, 1.15, 0.65], ph=(5.5, 6.5), n=(30, 60), p=(15, 35), k=(120, 200),
                         ec_max=1.5, humidite_sol=(45, 65), temp_opt=(21, 30), densite=40000,
                         debit_plant_lph=2, tol_hydrique=4),
    "Arachide": dict(categorie=CER, varietes=["Virginia", "Spanish"],
                     kc=[0.40, 0.80, 1.15, 0.60], ph=(5.8, 6.6), n=(20, 45), p=(20, 40), k=(80, 150),
                     ec_max=3.2, humidite_sol=(45, 65), temp_opt=(22, 32), densite=200000,
                     debit_plant_lph=1, tol_hydrique=4),
    "Papaye": dict(categorie=FRU, varietes=["Solo", "Formosa"],
                   kc=[0.60, 0.85, 1.05, 1.00], ph=(5.8, 6.8), n=(50, 90), p=(25, 45), k=(150, 250),
                   ec_max=1.2, humidite_sol=(55, 75), temp_opt=(24, 33), densite=2000,
                   debit_plant_lph=12, tol_hydrique=2),
    "Banane/Plantain": dict(categorie=FRU, varietes=["Plantain French", "Cavendish (dessert)"],
                            kc=[0.50, 0.90, 1.15, 1.10], ph=(5.8, 7.0), n=(60, 110), p=(25, 50), k=(200, 350),
                            ec_max=1.0, humidite_sol=(65, 85), temp_opt=(24, 32), densite=1700,
                            debit_plant_lph=16, tol_hydrique=1),
}

def plant_ns(nom, c):
    """Objet plante avec les mêmes attributs que la table `plants` de l'API."""
    return SimpleNamespace(
        nom=nom, ph_min=c["ph"][0], ph_max=c["ph"][1], n_min=c["n"][0], n_max=c["n"][1],
        p_min=c["p"][0], p_max=c["p"][1], k_min=c["k"][0], k_max=c["k"][1], ec_max_dsm=c["ec_max"],
        humidite_sol_min=c["humidite_sol"][0], humidite_sol_max=c["humidite_sol"][1],
        temp_opt_min=c["temp_opt"][0], temp_opt_max=c["temp_opt"][1],
        kc_germination=c["kc"][0], kc_vegetative=c["kc"][1], kc_floraison=c["kc"][2], kc_fructification=c["kc"][3],
        densite_plants_ha=c["densite"], debit_plant_lph=c["debit_plant_lph"], tolerance_hydrique=c["tol_hydrique"])


PLANTS = {nom: plant_ns(nom, c) for nom, c in CATALOGUE.items()}

STAGES = ["Germination", "Croissance végétative", "Floraison", "Fructification/Maturation"]
SOILS = ["Sableux", "Limoneux", "Argileux"]
SOIL_P = [0.30, 0.45, 0.25]
SOIL_PARAMS = {  # décalage d'humidité, rétention nutriments, EC de base, facteur de pertes d'eau
    "Sableux":  dict(hum=-8, nut=0.85, ec=0.6, perte=1.15),
    "Limoneux": dict(hum=0,  nut=1.00, ec=0.9, perte=1.00),
    "Argileux": dict(hum=6,  nut=1.10, ec=1.2, perte=0.90),
}
HEALTH = ["Saine", "Carence en N", "Carence en P", "Carence en K",
          "Stress thermique", "Attaque Fongique/Parasitaire"]
HEALTH_P = [0.46, 0.11, 0.08, 0.08, 0.13, 0.14]


def mid(r):
    return (r[0] + r[1]) / 2


# --------------------------------------------------------------------------------------
# 2. DATASET PÉDOLOGIQUE
# --------------------------------------------------------------------------------------
def gen_pedologique(n_rows, rng):
    rows = []
    plants = list(CATALOGUE)
    for _ in range(n_rows):
        plante = rng.choice(plants)
        c = CATALOGUE[plante]
        variete = rng.choice(c["varietes"])
        sol = rng.choice(SOILS, p=SOIL_P)
        sp = SOIL_PARAMS[sol]
        etat = rng.choice(HEALTH, p=HEALTH_P)

        ph = rng.normal(mid(c["ph"]), 0.35)
        hum = rng.normal(mid(c["humidite_sol"]) + sp["hum"], 6)
        temp = rng.normal(mid(c["temp_opt"]) - 1, 2.5)
        N = rng.normal(mid(c["n"]), 0.12 * mid(c["n"])) * sp["nut"]
        P = rng.normal(mid(c["p"]), 0.12 * mid(c["p"])) * sp["nut"]
        K = rng.normal(mid(c["k"]), 0.12 * mid(c["k"])) * sp["nut"]
        ec = abs(rng.normal(sp["ec"], 0.25))
        if rng.random() < 0.06:  # sols salins occasionnels
            ec = c["ec_max"] * rng.uniform(1.1, 1.8)
        if rng.random() < 0.10:  # sols mal calibrés en pH
            ph += rng.choice([-1, 1]) * rng.uniform(0.8, 1.5)

        if etat == "Carence en N":
            N *= rng.uniform(0.25, 0.60)
        elif etat == "Carence en P":
            P *= rng.uniform(0.25, 0.60)
        elif etat == "Carence en K":
            K *= rng.uniform(0.25, 0.60)
        elif etat == "Stress thermique":
            temp = c["temp_opt"][1] + rng.uniform(5, 10)
            hum -= rng.uniform(8, 20)
        elif etat == "Attaque Fongique/Parasitaire":
            hum = min(95, c["humidite_sol"][1] + rng.uniform(8, 20))
            temp = rng.uniform(22, 30)

        ph = float(np.clip(ph, 3.8, 8.8))
        hum = float(np.clip(hum, 5, 95))
        temp = float(np.clip(temp, 15, 50))
        N, P, K = (float(max(1, v)) for v in (N, P, K))
        rows.append({
            "ph": round(ph, 2), "humidite_sol_pct": round(hum, 1), "temperature_sol_c": round(temp, 1),
            "azote_N_mgkg": round(N, 1), "phosphore_P_mgkg": round(P, 1), "potassium_K_mgkg": round(K, 1),
            "conductivite_ec_dsm": round(ec, 2), "type_sol": sol,
            "plante": plante, "variete": variete, "etat_sante": etat,
            "recommandation": texte_complet(conseils_diagnostic(PLANTS[plante], etat, {
                "ph": round(ph, 2), "humidite_sol": round(hum, 1), "temperature_sol": round(temp, 1),
                "N": round(N, 1), "P": round(P, 1), "K": round(K, 1), "ec": round(ec, 2), "type_sol": sol})).replace("\n", " "),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# 3. DATASET IRRIGATION : produit avec le moteur de l'API (diagnostic -> arrosage), plus du bruit
# --------------------------------------------------------------------------------------
def gen_irrigation(n_rows, rng):
    rows = []
    plants = list(CATALOGUE)
    for _ in range(n_rows):
        plante = rng.choice(plants)
        c = CATALOGUE[plante]
        ns = PLANTS[plante]
        variete = rng.choice(c["varietes"])
        stade_i = int(rng.choice(4, p=[0.12, 0.34, 0.26, 0.28]))
        stade = STAGES[stade_i]
        sol = rng.choice(SOILS, p=SOIL_P)
        sp = SOIL_PARAMS[sol]
        etat = rng.choice(HEALTH, p=HEALTH_P)
        salinite = bool(rng.random() < 0.08)

        t_air = round(float(np.clip(rng.normal(27, 4), 17, 40)), 1)
        rh = round(float(np.clip(rng.normal(70, 14), 25, 100)), 1)
        h_lo, h_hi = c["humidite_sol"]
        hum = rng.normal(mid(c["humidite_sol"]) + sp["hum"] - 4, 12)
        if etat == "Attaque Fongique/Parasitaire" and rng.random() < 0.7:   # sol détrempé dans 70 % des cas
            hum = h_hi + rng.uniform(8, 20)
        elif etat == "Stress thermique":
            hum -= rng.uniform(8, 20)
        hum = round(float(np.clip(hum, 5, 95)), 1)
        pluie = round(float(rng.gamma(2.0, 3.0)), 1) if rng.random() < 0.25 else 0.0
        surface = float(rng.choice([250, 500, 750, 1000, 1500, 2000]))

        d = estimer_irrigation(ns, stade, t_air, rh, hum, sol, pluie, surface,
                               etat_sante=etat, salinite_elevee=salinite)
        litres_plant = d.besoin_L_par_plant_jour * (rng.normal(1.0, 0.04) if d.vanne_ouverte else 1.0)
        duree = min(240, round(litres_plant / (c["debit_plant_lph"] / 60))) if d.vanne_ouverte else 0

        rows.append({
            "plante": plante, "variete": variete, "stade_croissance": stade,
            "temperature_air_c": t_air, "humidite_air_pct": rh, "humidite_sol_pct": hum,
            "type_sol": sol, "etat_sante": etat, "salinite_elevee": int(salinite),
            "diagnostic_pedologique": f"Sol {sol.lower()} - {etat}",
            "prevision_pluie_6h_mm": pluie, "et0_mm_jour": d.et0_mm_jour, "kc_applique": d.kc,
            "surface_par_plant_m2": round(10000 / c["densite"], 5), "surface_parcelle_m2": surface,
            "besoin_eau_L_par_plant_jour": round(litres_plant, 4),
            "besoin_eau_L_parcelle_jour": round(litres_plant * d.nb_plants, 1),
            "etat_vanne": "Ouverte" if d.vanne_ouverte else "Fermée",
            "duree_irrigation_min": int(duree), "code_decision": d.code_decision,
            "motif_decision": d.motif,
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# 4. EXPORT
# --------------------------------------------------------------------------------------
def export_catalogue(path):
    out = []
    for nom, c in CATALOGUE.items():
        out.append({
            "nom": nom, "categorie": c["categorie"], "varietes": c["varietes"],
            "kc": dict(zip(["germination", "vegetative", "floraison", "fructification"], c["kc"])),
            "ph_min": c["ph"][0], "ph_max": c["ph"][1],
            "n_min": c["n"][0], "n_max": c["n"][1], "p_min": c["p"][0], "p_max": c["p"][1],
            "k_min": c["k"][0], "k_max": c["k"][1], "ec_max_dsm": c["ec_max"],
            "humidite_sol_min": c["humidite_sol"][0], "humidite_sol_max": c["humidite_sol"][1],
            "temp_opt_min": c["temp_opt"][0], "temp_opt_max": c["temp_opt"][1],
            "densite_plants_ha": c["densite"], "debit_plant_lph": c["debit_plant_lph"],
            "tolerance_hydrique": c["tol_hydrique"],
        })
    Path(path).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-pedo", type=int, default=6000)
    ap.add_argument("--n-irrig", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=".")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(a.seed)

    df1 = gen_pedologique(a.n_pedo, rng)
    df1.to_csv(out / "dataset_pedologique.csv", index=False, encoding="utf-8-sig")
    df2 = gen_irrigation(a.n_irrig, rng)
    df2.to_csv(out / "dataset_irrigation.csv", index=False, encoding="utf-8-sig")
    export_catalogue(out / "catalogue_plantes.json")

    print(f"dataset_pedologique.csv : {len(df1)} lignes")
    print(df1["etat_sante"].value_counts(normalize=True).round(3).to_string(), "\n")
    print(f"dataset_irrigation.csv  : {len(df2)} lignes")
    print(df2["etat_vanne"].value_counts(normalize=True).round(3).to_string())


if __name__ == "__main__":
    main()
