"""
Moteur d'irrigation : formule FAO-56 simplifiée + ajustement selon le diagnostic du sol
+ correction facultative par un modèle ML (avec garde-fou).

Ordre logique du système :  1) diagnostic du sol  ->  2) calcul de l'arrosage.
Les paramètres de la plante (Kc, plages d'humidité, densité, débit) viennent de la base : ajouter ou
modifier une plante change immédiatement les recommandations. Fonctions pures, faciles à tester.
"""
import math
import os
from dataclasses import dataclass
from pathlib import Path

RA_MM_JOUR = 15.5          # rayonnement extraterrestre, zone équatoriale (équivalent mm/jour)
EFFICIENCE = 0.90          # goutte-à-goutte
PLUIE_REPORT_MM = 5.0      # pluie prévue (6 h) à partir de laquelle on reporte l'irrigation
PLUIE_LEGERE_MM = 2.0      # entre 2 et 5 mm : volume réduit de moitié
DUREE_MAX_MIN = 240
GARDE_FOU = (0.7, 1.3)     # le ML ne peut s'écarter de la formule que de ±30 %
CONSEIL_HORAIRE_DEFAUT = "Le mieux : arroser tôt le matin ou en fin d'après-midi."

MODELE_PAR_DEFAUT = Path(__file__).resolve().parents[4] / "ml" / "registry" / "irrigation_latest.joblib"

STADES = {
    "Germination": "kc_germination",
    "Croissance végétative": "kc_vegetative",
    "Floraison": "kc_floraison",
    "Fructification/Maturation": "kc_fructification",
}
PERTES_SOL = {"Sableux": 1.15, "Limoneux": 1.00, "Argileux": 0.90}

FEATURES_IRRIGATION = [
    "deficit", "tolerance_hydrique", "kc", "et0", "t_air", "humidite_air", "pluie_6h",
    "sol_sableux", "sol_argileux", "etat_fongique", "etat_thermique", "salinite",
]


@dataclass
class Decision:
    et0_mm_jour: float
    kc: float
    nb_plants: int
    besoin_L_par_plant_jour: float
    besoin_L_parcelle_jour: float
    vanne_ouverte: bool
    duree_min: int
    code_decision: str        # irrigation | pluie_legere | pluie_forte | sol_humide
    motif: str
    resume: str
    conseil_horaire: str
    ajustement: str | None
    methode: str              # formule | ml | formule (garde-fou)


def et0_hargreaves(t_air: float, humidite_air: float) -> float:
    """ET0 (mm/jour). L'amplitude thermique est estimée à partir de l'humidité de l'air."""
    amplitude = min(14.0, max(5.0, 14 - 0.08 * humidite_air))
    return 0.0023 * (t_air + 17.8) * math.sqrt(amplitude) * RA_MM_JOUR


def deficit_hydrique(plant, humidite_sol: float) -> float:
    """0 = sol à l'humidité maximale idéale ; 0,5 = milieu de la plage (seuil de déclenchement) ;
    1 ou plus = sol à l'humidité minimale idéale ou en dessous."""
    return (plant.humidite_sol_max - humidite_sol) / (plant.humidite_sol_max - plant.humidite_sol_min)


def ajustement_diagnostic(etat_sante: str, salinite_elevee: bool, pluie_6h_mm: float):
    """Le diagnostic du sol corrige le volume d'eau. Retourne (facteur, explication, conseil horaire)."""
    facteur, raisons, horaire = 1.0, [], None
    if etat_sante == "Attaque Fongique/Parasitaire":
        facteur *= 0.6
        raisons.append("Le sol risque d'avoir trop d'humidité (maladies) : on réduit l'eau de 40 %.")
        horaire = "Arrosez seulement le matin, au pied des plants, sans mouiller les feuilles."
    elif etat_sante == "Stress thermique":
        facteur *= 1.2
        raisons.append("Le sol est trop chaud : on ajoute 20 % d'eau pour le rafraîchir.")
        horaire = "Arrosez tôt le matin (avant 9 h) ou après 17 h, jamais en plein soleil."
    if salinite_elevee and pluie_6h_mm < PLUIE_LEGERE_MM:
        facteur *= 1.15
        raisons.append("Il y a trop de sel dans le sol : on ajoute 15 % d'eau pour le laver.")
    return facteur, " ".join(raisons) or None, horaire


def features_irrigation(plant, stade, t_air, humidite_air, humidite_sol, type_sol, pluie_6h_mm,
                        etat_sante="Saine", salinite_elevee=False) -> list[float]:
    """Variables du modèle ML d'irrigation (partagées avec ml/train_irrigation.py)."""
    return [
        deficit_hydrique(plant, humidite_sol), float(plant.tolerance_hydrique), float(getattr(plant, STADES[stade])),
        et0_hargreaves(t_air, humidite_air), float(t_air), float(humidite_air), float(pluie_6h_mm),
        float(type_sol == "Sableux"), float(type_sol == "Argileux"),
        float(etat_sante == "Attaque Fongique/Parasitaire"), float(etat_sante == "Stress thermique"),
        float(salinite_elevee),
    ]


_cache = {"path": None, "mtime": None, "bundle": None}


def charger_modele():
    path = Path(os.getenv("IRRIGATION_MODEL_PATH", MODELE_PAR_DEFAUT))
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    if _cache["path"] != path or _cache["mtime"] != mtime:
        import joblib
        _cache.update(path=path, mtime=mtime, bundle=joblib.load(path))
    return _cache["bundle"]


def fonction_prediction():
    """Retourne une fonction « variables -> ratio » si un modèle est installé, sinon None."""
    bundle = charger_modele()
    if bundle is None:
        return None
    return lambda feats: float(bundle["model"].predict([feats])[0])


def _fmt(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def _litres(x: float) -> str:
    return f"{x:.1f}".replace(".", ",") + (" litre" if x < 2 else " litres")


def estimer_irrigation(plant, stade: str, t_air: float, humidite_air: float, humidite_sol: float,
                       type_sol: str, pluie_6h_mm: float, surface_parcelle_m2: float,
                       etat_sante: str = "Saine", salinite_elevee: bool = False,
                       predire_ratio=None) -> Decision:
    if stade not in STADES:
        raise ValueError(f"Stade inconnu : {stade}")
    kc = getattr(plant, STADES[stade])
    et0 = et0_hargreaves(t_air, humidite_air)
    surface_par_plant = 10000 / plant.densite_plants_ha
    etc_litres_plant = kc * et0 * surface_par_plant

    # Étape 1 : le diagnostic du sol corrige le volume ; étape 2 : calcul de l'arrosage
    facteur_diag, ajustement, horaire = ajustement_diagnostic(etat_sante, salinite_elevee, pluie_6h_mm)
    deficit = deficit_hydrique(plant, humidite_sol)
    # Seuil de déclenchement au milieu de la plage idéale : on n'arrose pas dès que le sol quitte le maximum
    facteur = (0.5 + 0.5 * min(deficit, 1.0)) if deficit > 0.5 else 0.0
    facteur *= 1.0 + (3 - plant.tolerance_hydrique) * 0.04   # plante sensible : on irrigue plus franchement
    litres_plant = max(0.0, etc_litres_plant * facteur * PERTES_SOL[type_sol] / EFFICIENCE * facteur_diag)

    if pluie_6h_mm >= PLUIE_REPORT_MM:
        ouverte, litres_plant, code = False, 0.0, "pluie_forte"
        motif = (f"Une pluie de {pluie_6h_mm:.1f} mm est annoncée dans les 6 prochaines heures : "
                 "inutile d'arroser, la pluie s'en charge.")
    elif litres_plant <= 0:
        ouverte, code = False, "sol_humide"
        motif = "Le sol est encore assez humide pour la plante."
    elif pluie_6h_mm >= PLUIE_LEGERE_MM:
        ouverte, code = True, "pluie_legere"
        litres_plant *= 0.5
        motif = f"Une petite pluie ({pluie_6h_mm:.1f} mm) est annoncée : on arrose deux fois moins."
    else:
        ouverte, code = True, "irrigation"
        motif = "Le sol commence à se dessécher : il faut arroser."

    methode = "formule"
    if ouverte and predire_ratio is not None and etc_litres_plant > 0:
        litres_ml = predire_ratio(features_irrigation(plant, stade, t_air, humidite_air, humidite_sol,
                                                      type_sol, pluie_6h_mm, etat_sante, salinite_elevee)) * etc_litres_plant
        bas, haut = GARDE_FOU
        if bas * litres_plant <= litres_ml <= haut * litres_plant:
            litres_plant, methode = litres_ml, "ml"
        else:
            methode = "formule (garde-fou)"

    nb_plants = round(surface_parcelle_m2 * plant.densite_plants_ha / 10000)
    litres_parcelle = litres_plant * nb_plants
    duree = min(DUREE_MAX_MIN, round(litres_plant / (plant.debit_plant_lph / 60))) if ouverte else 0

    if ouverte:
        resume = (f"Arrosez la parcelle de {plant.nom} : environ {_fmt(litres_parcelle)} litres au total "
                  f"({_litres(litres_plant)} par plant), pendant {duree} minutes.")
    else:
        resume = f"Pas d'arrosage pour la parcelle de {plant.nom}. {motif}"
    if not ouverte:
        ajustement = None      # « on ajoute 20 % d'eau » n'a pas de sens si on n'arrose pas
    return Decision(round(et0, 2), kc, nb_plants, round(litres_plant, 4), round(litres_parcelle, 1),
                    ouverte, duree, code, motif, resume, horaire or CONSEIL_HORAIRE_DEFAUT,
                    ajustement, methode)
