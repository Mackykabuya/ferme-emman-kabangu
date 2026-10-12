#!/usr/bin/env python3
"""
Entraînement du modèle de diagnostic pédologique.

  python ml/train_diagnostic.py            (depuis la racine du projet)

1. Mesure la précision classique (80 % entraînement / 20 % test).
2. Mesure la généralisation à une plante JAMAIS VUE : on entraîne sur 12 plantes et on teste
   sur la 13e, tour à tour (« leave-one-plant-out »). C'est le test qui compte pour l'ajout
   dynamique de plantes.
3. Entraîne le modèle final sur toutes les données et l'enregistre dans ml/registry/.

ATTENTION : les datasets sont synthétiques (générés avec des règles connues) ; les scores sont donc
optimistes. Ils valident la chaîne technique, pas la performance réelle sur le terrain.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import joblib
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict, train_test_split

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "apps" / "api"))
from app.engine.diagnostic import ETATS, FEATURES, features_from  # noqa: E402  (code partagé avec l'API)

DATA = RACINE / "ml" / "data"
REGISTRY = RACINE / "ml" / "registry"


def nouveau_modele():
    return RandomForestClassifier(n_estimators=200, min_samples_leaf=2, class_weight="balanced",
                                  n_jobs=-1, random_state=42)


def main():
    df = pd.read_csv(DATA / "dataset_pedologique.csv", encoding="utf-8-sig")
    catalogue = {c["nom"]: SimpleNamespace(**c) for c in json.loads((DATA / "catalogue_plantes.json").read_text(encoding="utf-8"))}

    X, y, groupes = [], [], []
    for r in df.itertuples(index=False):
        m = {"ph": r.ph, "humidite_sol": r.humidite_sol_pct, "temperature_sol": r.temperature_sol_c,
             "N": r.azote_N_mgkg, "P": r.phosphore_P_mgkg, "K": r.potassium_K_mgkg,
             "ec": r.conductivite_ec_dsm, "type_sol": r.type_sol}
        X.append(features_from(catalogue[r.plante], m))
        y.append(r.etat_sante)
        groupes.append(r.plante)
    print(f"{len(X)} exemples, {len(FEATURES)} variables, {len(set(groupes))} plantes\n")

    # 1. Précision classique
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)
    modele = nouveau_modele().fit(Xtr, ytr)
    pred = modele.predict(Xte)
    acc_classique = accuracy_score(yte, pred)
    print(f"[1] Précision (split 80/20) : {acc_classique:.3f}")
    print(classification_report(yte, pred, digits=3))
    print("Matrice de confusion (lignes = réel, colonnes = prédit) :")
    print(pd.DataFrame(confusion_matrix(yte, pred, labels=ETATS), index=ETATS, columns=[e[:10] for e in ETATS]), "\n")

    # 2. Généralisation à une plante jamais vue
    pred_cv = cross_val_predict(nouveau_modele(), X, y, groups=groupes, cv=LeaveOneGroupOut())
    par_plante = {p: accuracy_score([a for a, g in zip(y, groupes) if g == p],
                                    [b for b, g in zip(pred_cv, groupes) if g == p])
                  for p in sorted(set(groupes))}
    acc_inedite = accuracy_score(y, pred_cv)
    print(f"[2] Précision sur plante INÉDITE (leave-one-plant-out) : {acc_inedite:.3f}")
    for p, a in par_plante.items():
        print(f"    {p:<18} {a:.3f}")

    # 3. Modèle final
    final = nouveau_modele().fit(X, y)
    version = "v1-" + datetime.now().strftime("%Y%m%d-%H%M")
    bundle = {"model": final, "features": FEATURES, "version": version,
              "plantes_entrainement": sorted(set(groupes)), "sklearn": sklearn.__version__}
    REGISTRY.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, REGISTRY / "diagnostic_latest.joblib", compress=3)
    rapport = {"version": version, "date": datetime.now().isoformat(timespec="seconds"),
               "exemples": len(X), "precision_split": round(acc_classique, 4),
               "precision_plante_inedite": round(acc_inedite, 4),
               "precision_par_plante_inedite": {k: round(v, 4) for k, v in par_plante.items()},
               "plantes_entrainement": bundle["plantes_entrainement"],
               "importance_variables": dict(sorted(zip(FEATURES, map(lambda v: round(float(v), 4), final.feature_importances_)),
                                                   key=lambda kv: -kv[1]))}
    (REGISTRY / f"rapport_{version}.json").write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nModèle enregistré : ml/registry/diagnostic_latest.joblib ({version})")


if __name__ == "__main__":
    main()
