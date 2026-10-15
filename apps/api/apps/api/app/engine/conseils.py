"""
Conseils en langage simple pour l'agriculteur.
Règles : pas de jargon (pas de pH, EC, Kc...), des actions concrètes, des quantités en kg par « are »
(un are = un carré de 10 m x 10 m = 100 m²), et le total pour la parcelle quand on connaît sa surface.
Les doses sont indicatives : à confirmer avec un technicien agricole.
"""

LIBELLES = {
    "Saine": "Sol et plante en bonne santé",
    "Carence en N": "Manque d'azote (N)",
    "Carence en P": "Manque de phosphore (P)",
    "Carence en K": "Manque de potassium (K)",
    "Stress thermique": "Sol trop chaud",
    "Attaque Fongique/Parasitaire": "Risque de maladies (champignons) ou de parasites",
}


def _kg(x: float) -> str:
    v = round(x, 1) if x < 1 else (round(x * 2) / 2 if x < 10 else round(x))
    return f"{v:g}".replace(".", ",") + " kg"


def quantite(kg_par_are: float, surface_m2: float | None = None) -> str:
    txt = f"environ {_kg(kg_par_are)} par are (un carré de 10 m × 10 m)"
    if surface_m2:
        txt += f", soit environ {_kg(kg_par_are * surface_m2 / 100)} pour vos {surface_m2:.0f} m²"
    return txt


def _deficit(valeur: float, optimum: float) -> float:
    return min(1.0, max(0.0, (optimum - valeur) / optimum))


def conseils_diagnostic(plant, etat: str, m: dict, surface_m2: float | None = None) -> dict:
    sableux = m["type_sol"] == "Sableux"
    actions: list[str] = []
    surveiller: list[str] = []

    if etat == "Saine":
        message = "Le sol et la plante sont en bonne santé."
        actions.append("Continuez votre arrosage et votre fertilisation habituels.")
        surveiller.append("Refaites une mesure dans une semaine pour suivre l'évolution.")

    elif etat == "Carence en N":
        message = ("Le sol manque d'azote (N). Les feuilles risquent de jaunir "
                   "et la plante de pousser lentement.")
        n_opt = (plant.n_min + plant.n_max) / 2
        dose_n = round((20 + 100 * _deficit(m["N"], n_opt)) / 5) * 5          # kg d'azote par hectare
        uree_are = dose_n / 0.46 / 100                                          # l'urée contient 46 % d'azote
        fois = ("en trois petites doses espacées de 10 jours" if sableux
                else "en deux fois, à 2 semaines d'intervalle")
        actions += [
            f"Apportez de l'urée : {quantite(uree_are, surface_m2)}, {fois}. "
            "Déposez-la au pied des plants, sans toucher les feuilles.",
            "Sans engrais chimique : mélangez à la terre, autour des plants, 100 à 150 kg de compost "
            "ou de fumier bien décomposé par are.",
            "Arrosez légèrement après chaque apport pour que l'engrais pénètre dans le sol.",
        ]
        surveiller.append("Les nouvelles feuilles doivent reverdir en 10 à 15 jours. Sinon, refaites une mesure.")
        if sableux:
            surveiller.append("Votre sol est sableux : l'eau emporte vite l'engrais. "
                              "Mieux vaut de petites doses plus souvent qu'une grosse dose.")

    elif etat == "Carence en P":
        message = ("Le sol manque de phosphore (P). Les racines et la floraison seront faibles, "
                   "et les feuilles peuvent devenir violacées.")
        p_opt = (plant.p_min + plant.p_max) / 2
        dose_p = 30 + 40 * _deficit(m["P"], p_opt)                              # kg de P2O5 par hectare
        tsp_are = dose_p / 0.46 / 100                                           # TSP/DAP : 46 % de P2O5
        actions += [
            f"Apportez un engrais phosphaté (TSP ou DAP) : {quantite(tsp_are, surface_m2)}. "
            "Enterrez-le près des racines : le phosphore ne se déplace presque pas dans le sol.",
            "Alternative naturelle : de la poudre d'os, mélangée à la terre autour des plants.",
        ]
        surveiller.append("Le phosphore agit lentement : comptez 3 à 4 semaines avant de voir un changement.")
        surveiller.append("Il passe mal si le sol est trop acide ou trop calcaire : vérifiez aussi l'acidité du sol.")

    elif etat == "Carence en K":
        message = ("Le sol manque de potassium (K). Le bord des feuilles brunit "
                   "et les fruits seront de moins bonne qualité.")
        k_opt = (plant.k_min + plant.k_max) / 2
        dose_k = 40 + 60 * _deficit(m["K"], k_opt)                              # kg de K2O par hectare
        sulfate_are = dose_k / 0.50 / 100                                       # sulfate de potasse : 50 % de K2O
        fois = "en deux ou trois fois" if sableux else "en une ou deux fois"
        actions += [
            f"Apportez du sulfate de potasse : {quantite(sulfate_are, surface_m2)}, {fois}, au pied des plants.",
            "Alternative naturelle : 5 à 10 kg de cendres de bois par are, bien mélangées à la terre.",
        ]
        surveiller.append("Évitez le chlorure de potassium si le sol contient trop de sel.")

    elif etat == "Stress thermique":
        message = "Le sol est trop chaud pour cette plante. Les racines souffrent et la plante peut flétrir."
        actions += [
            "Couvrez le sol avec de la paille ou des herbes sèches, sur 5 à 8 cm d'épaisseur.",
            "Arrosez tôt le matin (avant 9 h) ou après 17 h, jamais en plein soleil.",
            "Si possible, installez une ombrière légère (filet ou branchages) de 11 h à 15 h.",
        ]
        surveiller.append("Une plante qui flétrit à midi mais se redresse le soir est seulement fatiguée par la chaleur. "
                          "Si elle reste flétrie le soir, il faut arroser davantage.")

    else:  # Attaque Fongique/Parasitaire
        message = ("Le sol est trop humide et trop chaud : les champignons et les maladies des racines "
                   "peuvent se développer.")
        actions += [
            "Arrosez moins : seulement le matin, au pied des plants, sans mouiller les feuilles.",
            "Améliorez le drainage : creusez de petites rigoles pour évacuer l'eau en trop.",
            "Arrachez les plants malades et éloignez-les de la parcelle (ne les mettez pas au compost).",
            "Si vous en trouvez, traitez avec un produit à base de cuivre (bouillie bordelaise) ou du Trichoderma.",
        ]
        surveiller += ["Ne replantez pas la même culture à cet endroit à la prochaine saison.",
                       "Si les plants continuent de dépérir, montrez-les à un technicien agricole."]

    # Points qui s'ajoutent quel que soit l'état
    extras = 0
    if m["ph"] < plant.ph_min - 0.4:
        actions.append("Le sol est trop acide : épandez de la chaux agricole ou de la dolomie "
                       "(10 à 20 kg par are) et mélangez-la à la terre de surface.")
        extras += 1
    elif m["ph"] > plant.ph_max + 0.4:
        actions.append("Le sol est trop basique (calcaire) : ajoutez beaucoup de compost "
                       "et évitez la chaux et les cendres.")
        extras += 1
    if m["ec"] > plant.ec_max_dsm:
        actions.append("Il y a trop de sel dans le sol : donnez un gros arrosage d'eau douce pour le laver, "
                       "et vérifiez que l'eau peut bien s'écouler.")
        surveiller.append("Évitez les engrais chimiques tant que le sol est salé.")
        extras += 1
    if etat == "Saine" and extras:
        message = "L'état général est bon, mais il y a un point à corriger dans le sol."

    return {"message_simple": message, "actions": actions, "a_surveiller": surveiller}


def texte_complet(c: dict) -> str:
    return c["message_simple"] + "\n- " + "\n- ".join(c["actions"])
