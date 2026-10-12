#!/usr/bin/env python3
"""
Entraînement du modèle d'irrigation.

  python ml/train_irrigation.py            (depuis la racine du projet)

Architecture « formule + correction ML » :
  - la formule FAO-56 calcule l'eau que la plante perd (ETc, en litres par plant) ;
  - le modèle ML prédit un RATIO : litres réellement nécessaires / litres d'ETc. Ce ratio est sans unité
    et comparable d'une plante à l'autre, donc le modèle fonctionne aussi pour une plante ajoutée plus tard ;
  - la décision d'ouvrir la vanne et la règle « pluie forte = pas d'arrosage » restent des RÈGLES, jamais du ML ;
  - en production, si le ML s'écarte de plus de 30 % de la formule, on garde la formule (garde-fou).

ATTENTION : les étiquettes du dataset viennent de la formule (plus 4 % de bruit). Le modèle apprend donc à
retrouver la formule : ses scores prouvent que la chaîne fonctionne, pas qu'il fait mieux qu'elle. Il deviendra
utile quand il sera réentraîné avec les vraies mesures de la ferme (volumes réellement apportés, humidité après arrosage).
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict, train_test_split

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "apps" / "api"))
from app.engine.irrigation import FEATURES_IRRIGATION, features_irrigation  # noqa: E402  (code partagé avec l'API)

DATA = RACINE / "ml" / "data"
REGISTRY = RACINE / "ml" / "registry"
BRUIT_DATASET = 0.04          # le dataset contient 4 % de bruit gaussien : plancher d'erreur incompressible


def nouveau_modele():
    return HistGradientBoostingRegressor(max_iter=400, learning_rate=0.06, max_leaf_nodes=24, random_state=42)


def metriques(reel, pred):
    reel, pred = np.asarray(reel), np.asarray(pred)
    err = np.abs(pred - reel) / reel
    ss_res, ss_tot = ((reel - pred) ** 2).sum(), ((reel - reel.mean()) ** 2).sum()
    return {"erreur_moyenne_pct": round(100 * err.mean(), 2), "dans_10_pct": round(100 * (err <= 0.10).mean(), 1),
            "r2": round(1 - ss_res / ss_tot, 4)}


def main():
    df = pd.read_csv(DATA / "dataset_irrigation.csv", encoding="utf-8-sig")
    catalogue = {c["nom"]: SimpleNamespace(
        nom=c["nom"], humidite_sol_min=c["humidite_sol_min"], humidite_sol_max=c["humidite_sol_max"],
        tolerance_hydrique=c["tolerance_hydrique"], kc_germination=c["kc"]["germination"],
        kc_vegetative=c["kc"]["vegetative"], kc_floraison=c["kc"]["floraison"],
        kc_fructification=c["kc"]["fructification"]) for c in json.loads((DATA / "catalogue_plantes.json").read_text(encoding="utf-8"))}

    ouvertes = df[(df.etat_vanne == "Ouverte") & (df.besoin_eau_L_par_plant_jour > 0)]
    X, y, groupes = [], [], []
    for r in ouvertes.itertuples(index=False):
        X.append(features_irrigation(catalogue[r.plante], r.stade_croissance, r.temperature_air_c, r.humidite_air_pct,
                                     r.humidite_sol_pct, r.type_sol, r.prevision_pluie_6h_mm, r.etat_sante,
                                     bool(r.salinite_elevee)))
        etc_litres = r.kc_applique * r.et0_mm_jour * r.surface_par_plant_m2
        y.append(r.besoin_eau_L_par_plant_jour / etc_litres)           # le ratio à prédire
        groupes.append(r.plante)
    print(f"{len(df)} situations dont {len(X)} avec vanne ouverte, {len(FEATURES_IRRIGATION)} variables, "
          f"{len(set(groupes))} plantes")
    print(f"Plancher d'erreur dû au bruit du dataset : ~{100 * BRUIT_DATASET * 0.8:.1f} %\n")

    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42)
    m1 = metriques(yte, nouveau_modele().fit(Xtr, ytr).predict(Xte))
    print(f"[1] Test classique 80/20 : erreur moyenne {m1['erreur_moyenne_pct']} % | "
          f"{m1['dans_10_pct']} % des prédictions à ±10 % | R² = {m1['r2']}")

    pred_cv = cross_val_predict(nouveau_modele(), X, y, groups=groupes, cv=LeaveOneGroupOut())
    m2 = metriques(y, pred_cv)
    print(f"[2] Plante INÉDITE (leave-one-plant-out) : erreur moyenne {m2['erreur_moyenne_pct']} % | "
          f"{m2['dans_10_pct']} % à ±10 % | R² = {m2['r2']}")
    par_plante = {}
    for p in sorted(set(groupes)):
        idx = [i for i, g in enumerate(groupes) if g == p]
        par_plante[p] = metriques([y[i] for i in idx], [pred_cv[i] for i in idx])["erreur_moyenne_pct"]
        print(f"    {p:<18} erreur moyenne {par_plante[p]} %")

    final = nouveau_modele().fit(X, y)
    version = "v1-" + datetime.now().strftime("%Y%m%d-%H%M")
    bundle = {"model": final, "features": FEATURES_IRRIGATION, "version": version,
              "plantes_entrainement": sorted(set(groupes)), "sklearn": sklearn.__version__}
    REGISTRY.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, REGISTRY / "irrigation_latest.joblib", compress=3)
    (REGISTRY / f"rapport_irrigation_{version}.json").write_text(json.dumps({
        "version": version, "date": datetime.now().isoformat(timespec="seconds"), "exemples": len(X),
        "test_classique": m1, "plante_inedite": m2, "erreur_par_plante_inedite_pct": par_plante,
        "plantes_entrainement": bundle["plantes_entrainement"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nModèle enregistré : ml/registry/irrigation_latest.joblib ({version})")


if __name__ == "__main__":
    main()
