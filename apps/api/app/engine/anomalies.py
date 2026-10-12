"""
Détection d'anomalies : repère les pannes de capteurs, de vannes et de pompe à partir de l'historique des mesures.

Fonctions pures (pas de base de données) : on leur donne les dernières mesures d'une parcelle, elles rendent des alertes
écrites en langage simple pour un agriculteur. Chaque alerte : code, gravité (critique | attention | info), titre,
message (ce qui se passe), conseil (quoi faire), parcelle.
"""
from __future__ import annotations

FENETRE_BLOQUE = 6        # nombre de mesures identiques de suite = capteur considéré muet
FENETRE_VANNE = 4         # mesures consécutives vanne ouverte avant de juger qu'elle n'arrose pas (≈ 40 min)
GAIN_MIN_VANNE = 0.3      # points d'humidité qu'une vanne qui marche apporte au minimum sur cette fenêtre

# Valeurs physiquement impossibles : au-delà, c'est le capteur qui se trompe, pas le sol.
LIMITES = {
    "humidite_sol_pct": (0.0, 100.0, "l'humidité du sol"),
    "ph": (0.0, 14.0, "l'acidité du sol (pH)"),
    "temperature_sol_c": (-5.0, 70.0, "la température du sol"),
    "conductivite_ec_dsm": (0.0, 20.0, "la salinité du sol"),
    "azote_N_mgkg": (0.0, 5000.0, "l'azote du sol"),
    "phosphore_P_mgkg": (0.0, 5000.0, "le phosphore du sol"),
    "potassium_K_mgkg": (0.0, 5000.0, "le potassium du sol"),
}


def _alerte(code: str, gravite: str, parcelle: str, titre: str, message: str, conseil: str, **extra) -> dict:
    return {"code": code, "gravite": gravite, "parcelle": parcelle, "titre": titre, "message": message, "conseil": conseil, **extra}


def _minutes(hist: list[dict]) -> int:
    return max(0, round((hist[-1]["at"] - hist[0]["at"]).total_seconds() / 60))


def capteur_bloque(hist: list[dict]) -> bool:
    """Toutes les valeurs identiques sur les dernières mesures : un vrai capteur bouge toujours un peu."""
    if len(hist) < FENETRE_BLOQUE:
        return False
    fin = hist[-FENETRE_BLOQUE:]
    return all(m["mesures"] == fin[0]["mesures"] for m in fin)


def valeur_impossible(hist: list[dict]) -> tuple[str, float] | None:
    if not hist:
        return None
    m = hist[-1]["mesures"]
    for cle, (bas, haut, _) in LIMITES.items():
        v = m.get(cle)
        if v is not None and (v < bas or v > haut or (cle == "humidite_sol_pct" and v == 0)):
            return cle, v
    return None


def capteur_suspect(hist: list[dict]) -> bool:
    """Utilisé pour suspendre l'arrosage automatique : on n'arrose pas sur la foi d'un capteur douteux."""
    return capteur_bloque(hist) or valeur_impossible(hist) is not None


def vanne_sans_effet(hist: list[dict]) -> list[dict]:
    """Renvoie la dernière période où la vanne est restée ouverte (au moins FENETRE_VANNE mesures) sans que le sol
    reçoive d'eau. On regarde tout l'historique fourni : l'alerte reste affichée un moment après la fermeture."""
    fautive, serie = [], []
    for m in hist + [{"vanne_ouverte": False}]:
        if m["vanne_ouverte"]:
            serie.append(m)
            continue
        if len(serie) >= FENETRE_VANNE:
            hums = [m["mesures"]["humidite_sol_pct"] for m in serie]
            fiable = all(0 < h <= 100 for h in hums) and any(m["mesures"] != serie[0]["mesures"] for m in serie)   # capteur qui ment : on ne juge pas la vanne
            if fiable and hums[-1] < 90 and hums[-1] - hums[0] < GAIN_MIN_VANNE:
                fautive = serie
        serie = []
    return fautive


def analyser_parcelle(nom: str, hist: list[dict], debit_besoin_lh: float | None = None, debit_pompe_lh: float | None = None) -> list[dict]:
    """hist : mesures de la plus ancienne à la plus récente, chacune {"at": datetime, "mesures": dict, "vanne_ouverte": bool}."""
    alertes: list[dict] = []
    imp = valeur_impossible(hist)
    if imp:
        cle, v = imp
        alertes.append(_alerte(
            "valeur_impossible", "critique", nom, "Capteur qui se trompe",
            f"Le capteur de « {nom} » donne une valeur impossible pour {LIMITES[cle][2]} ({v:g}). Il est probablement débranché ou cassé.",
            "Vérifiez la sonde et son câble. L'arrosage automatique de cette parcelle est suspendu tant que la valeur n'est pas normale.",
            champ=cle, valeur=v))
    elif capteur_bloque(hist):
        alertes.append(_alerte(
            "capteur_bloque", "attention", nom, "Capteur muet",
            f"Le capteur de « {nom} » envoie exactement la même valeur depuis {_minutes(hist[-FENETRE_BLOQUE:])} minutes. Il est peut-être en panne.",
            "Vérifiez la sonde et son câble. L'arrosage automatique de cette parcelle est suspendu en attendant."))
    periode = vanne_sans_effet(hist)
    if periode:
        alertes.append(_alerte(
            "vanne_sans_effet", "critique", nom, "La vanne n'arrose pas",
            f"La vanne de « {nom} » est restée ouverte {_minutes(periode)} minutes sans que le sol reçoive d'eau. "
            "Il y a peut-être une fuite, un tuyau bouché ou la pompe ne tourne pas.",
            "Allez voir la conduite sur place. Fermez la vanne si de l'eau se perd."))
    if debit_besoin_lh and debit_pompe_lh and debit_besoin_lh > debit_pompe_lh:
        alertes.append(_alerte(
            "pompe_trop_faible", "info", nom, "Pompe trop faible",
            f"Arroser « {nom} » demande {round(debit_besoin_lh):,} litres par heure, la pompe n'en donne que {round(debit_pompe_lh):,}.".replace(",", " "),
            "Arrosez cette parcelle par secteurs, ou prévoyez une pompe plus puissante."))
    return alertes
