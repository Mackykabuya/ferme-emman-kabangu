"""10 parcelles de démonstration (≈ 4,75 ha) avec des situations différentes pour illustrer le tableau de bord."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Plant
from .models_parcelles import Parcelle


def mesures_defaut(p, **modif) -> dict:
    mid = lambda a, b: (a + b) / 2
    m = {"humidite_sol_pct": round(mid(p.humidite_sol_min, p.humidite_sol_max) - 8), "temperature_sol_c": 26,
         "ph": round(mid(p.ph_min, p.ph_max), 1), "conductivite_ec_dsm": round(p.ec_max_dsm * 0.5, 2),
         "azote_N_mgkg": round(mid(p.n_min, p.n_max)), "phosphore_P_mgkg": round(mid(p.p_min, p.p_max)),
         "potassium_K_mgkg": round(mid(p.k_min, p.k_max))}
    m.update(modif)
    return m


DEMO = [  # nom, culture, m², sol, stade, ce qui sort de l'ordinaire
    ("Parcelle A1", "Maïs", 8000, "Limoneux", "Croissance végétative", lambda p: {"azote_N_mgkg": round((p.n_min + p.n_max) / 2 * 0.4)}),
    ("Parcelle A2", "Manioc", 7000, "Sableux", "Croissance végétative", lambda p: {}),
    ("Parcelle B1", "Banane/Plantain", 6000, "Argileux", "Fructification/Maturation", lambda p: {"humidite_sol_pct": p.humidite_sol_max + 12}),
    ("Parcelle B2", "Arachide", 5000, "Sableux", "Floraison", lambda p: {}),
    ("Parcelle C1", "Patate douce", 4500, "Limoneux", "Croissance végétative", lambda p: {"temperature_sol_c": 38}),
    ("Parcelle C2", "Papaye", 3500, "Limoneux", "Fructification/Maturation", lambda p: {}),
    ("Parcelle D1", "Tomate", 4000, "Limoneux", "Floraison", lambda p: {"humidite_sol_pct": p.humidite_sol_max - 1}),
    ("Parcelle D2", "Piment", 3000, "Sableux", "Floraison", lambda p: {}),
    ("Parcelle E1", "Gombo", 3500, "Limoneux", "Fructification/Maturation", lambda p: {"conductivite_ec_dsm": round(p.ec_max_dsm * 2, 2)}),
    ("Parcelle E2", "Chou", 3000, "Argileux", "Croissance végétative", lambda p: {}),
]


def seed_parcelles(db: Session) -> int:
    if db.scalar(select(func.count(Parcelle.id))):
        return 0
    plantes = {p.nom: p for p in db.scalars(select(Plant))}
    n = 0
    for nom, culture, surface, sol, stade, modif in DEMO:
        if culture in plantes:
            p = plantes[culture]
            db.add(Parcelle(nom=nom, surface_m2=surface, type_sol=sol, plant_id=p.id, stade=stade,
                            mesures=mesures_defaut(p, **modif(p))))
            n += 1
    db.commit()
    return n
