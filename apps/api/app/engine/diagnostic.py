"""
Diagnostic pédologique : variables relatives à la plante + modèle ML (ou règles de secours).

Le modèle ne reçoit pas « la plante » comme catégorie, mais des écarts par rapport à ses plages
optimales : une plante ajoutée plus tard au catalogue est diagnostiquée sans réentraînement.
Ce module est partagé par l'API et par ml/train_diagnostic.py (pas de décalage possible).
"""
import os
from pathlib import Path

from .conseils import LIBELLES, conseils_diagnostic, texte_complet

MODELE_PAR_DEFAUT = Path(__file__).resolve().parents[4] / "ml" / "registry" / "diagnostic_latest.joblib"

FEATURES = [
    "ph_ecart", "humidite_ecart", "humidite_exces", "humidite_deficit",
    "temp_ecart", "temp_exces", "temp_deficit",
    "n_ratio", "p_ratio", "k_ratio", "ec_ratio",
    "sol_sableux", "sol_limoneux", "sol_argileux",
]
ETATS = list(LIBELLES)


def features_dict(plant, m: dict) -> dict:
    """m : ph, humidite_sol, temperature_sol, N, P, K, ec, type_sol."""
    def mid(a, b): return (a + b) / 2
    def half(a, b): return (b - a) / 2
    h_min, h_max = plant.humidite_sol_min, plant.humidite_sol_max
    t_min, t_max = plant.temp_opt_min, plant.temp_opt_max
    return {
        "ph_ecart": (m["ph"] - mid(plant.ph_min, plant.ph_max)) / half(plant.ph_min, plant.ph_max),
        "humidite_ecart": (m["humidite_sol"] - mid(h_min, h_max)) / half(h_min, h_max),
        "humidite_exces": max(0.0, m["humidite_sol"] - h_max),
        "humidite_deficit": max(0.0, h_min - m["humidite_sol"]),
        "temp_ecart": (m["temperature_sol"] - mid(t_min, t_max)) / half(t_min, t_max),
        "temp_exces": max(0.0, m["temperature_sol"] - t_max),
        "temp_deficit": max(0.0, t_min - m["temperature_sol"]),
        "n_ratio": m["N"] / mid(plant.n_min, plant.n_max),
        "p_ratio": m["P"] / mid(plant.p_min, plant.p_max),
        "k_ratio": m["K"] / mid(plant.k_min, plant.k_max),
        "ec_ratio": m["ec"] / plant.ec_max_dsm,
        "sol_sableux": float(m["type_sol"] == "Sableux"),
        "sol_limoneux": float(m["type_sol"] == "Limoneux"),
        "sol_argileux": float(m["type_sol"] == "Argileux"),
    }


def features_from(plant, m: dict) -> list[float]:
    d = features_dict(plant, m)
    return [d[k] for k in FEATURES]


def regles_diagnostic(plant, m: dict) -> str:
    """Diagnostic de secours (sans ML), à partir des seuils agronomiques de la plante."""
    f = features_dict(plant, m)
    if f["temp_exces"] > 4:
        return "Stress thermique"
    if f["humidite_exces"] > 5 and 21 <= m["temperature_sol"] <= 31:
        return "Attaque Fongique/Parasitaire"
    ratios = {"Carence en N": f["n_ratio"], "Carence en P": f["p_ratio"], "Carence en K": f["k_ratio"]}
    etat, ratio = min(ratios.items(), key=lambda kv: kv[1])
    return etat if ratio < 0.65 else "Saine"


def recommandation(plant, etat: str, m: dict, surface_m2: float | None = None) -> str:
    return texte_complet(conseils_diagnostic(plant, etat, m, surface_m2))


_cache = {"path": None, "mtime": None, "bundle": None}


def charger_modele():
    """Charge le modèle s'il existe (rechargé automatiquement si le fichier change). Sinon None."""
    path = Path(os.getenv("DIAGNOSTIC_MODEL_PATH", MODELE_PAR_DEFAUT))
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    if _cache["path"] != path or _cache["mtime"] != mtime:
        import joblib  # import tardif : l'API démarre même sans scikit-learn
        _cache.update(path=path, mtime=mtime, bundle=joblib.load(path))
    return _cache["bundle"]


def diagnostiquer(plant, m: dict, surface_m2: float | None = None) -> dict:
    bundle = charger_modele()
    out = {"mode": "regles", "modele_version": None, "confiance": None, "probabilites": None,
           "plante_connue_du_modele": None, "avertissement": None}
    if bundle is None:
        out["etat_sante"] = regles_diagnostic(plant, m)
        out["avertissement"] = ("Le modèle intelligent n'est pas encore installé : "
                                "ce résultat vient de règles simples.")
    else:
        proba = bundle["model"].predict_proba([features_from(plant, m)])[0]
        classes = list(bundle["model"].classes_)
        meilleur = max(range(len(classes)), key=lambda i: proba[i])
        out.update(mode="ml", etat_sante=classes[meilleur], confiance=round(float(proba[meilleur]), 3),
                   probabilites={c: round(float(p), 3) for c, p in sorted(zip(classes, proba), key=lambda x: -x[1])},
                   modele_version=bundle["version"],
                   plante_connue_du_modele=plant.nom in bundle["plantes_entrainement"])
        notes = []
        if not out["plante_connue_du_modele"]:
            notes.append("Cette plante est nouvelle pour le système : ce résultat est une bonne estimation, "
                         "mais faites-le confirmer par un technicien agricole.")
        if out["confiance"] < 0.5:
            notes.append("Le système n'est pas très sûr de ce résultat : refaites une mesure "
                         "ou faites analyser le sol.")
        out["avertissement"] = " ".join(notes) or None
    conseils = conseils_diagnostic(plant, out["etat_sante"], m, surface_m2)
    out.update(etat_sante_libelle=LIBELLES[out["etat_sante"]], message_simple=conseils["message_simple"],
               actions=conseils["actions"], a_surveiller=conseils["a_surveiller"],
               recommandation=texte_complet(conseils))
    return out
