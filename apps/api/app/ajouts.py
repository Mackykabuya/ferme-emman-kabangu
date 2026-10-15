"""Ajouts de données faits UNE SEULE FOIS, même sur une base déjà remplie (le jeu de démonstration, lui, n'est chargé
que sur une base vide). Un marqueur est écrit en base : si vous supprimez ensuite une de ces parcelles ou plantes, elle
ne revient pas au démarrage suivant.

Ajout du 2026-10 : deux cultures pérennes, l'avocatier et le palmier à huile, avec une parcelle chacune (F1 et F2).
Les valeurs agronomiques sont des valeurs de référence (FAO-56, pratiques courantes en Afrique centrale) à faire valider
par votre agronome : tout se corrige ensuite dans la page « Catalogue » sans toucher au code."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Mapped, mapped_column, Session
from sqlalchemy import DateTime, String

from .database import Base
from .models import Plant, PlantHistory, PlantVariety
from .models_parcelles import Parcelle
from .schemas import PARAM_FIELDS
from .seed_parcelles import mesures_defaut

IDENTIFIANT = "avocatier-palmier-2026-10"


class AjoutFait(Base):
    __tablename__ = "ajouts_faits"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    fait_le: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


PLANTES = [
    dict(nom="Avocatier", categorie="Fruits / Autres", varietes=["Fuerte", "Hass", "Locale"],
         kc_germination=0.55, kc_vegetative=0.70, kc_floraison=0.80, kc_fructification=0.85,
         ph_min=5.5, ph_max=6.8, n_min=40, n_max=80, p_min=15, p_max=35, k_min=120, k_max=220,
         ec_max_dsm=1.0,                                   # très sensible au sel
         humidite_sol_min=55, humidite_sol_max=72,         # sol frais mais jamais détrempé (pourriture des racines)
         temp_opt_min=20, temp_opt_max=28, tolerance_hydrique=2, densite_plants_ha=150, debit_plant_lph=80),
    dict(nom="Palmier à huile", categorie="Fruits / Autres", varietes=["Tenera (hybride)", "Dura (locale)"],
         kc_germination=0.60, kc_vegetative=0.85, kc_floraison=0.95, kc_fructification=1.00,
         ph_min=4.8, ph_max=6.5, n_min=50, n_max=90, p_min=15, p_max=30, k_min=150, k_max=300,
         ec_max_dsm=1.8,
         humidite_sol_min=60, humidite_sol_max=85,         # grande consommation d'eau
         temp_opt_min=24, temp_opt_max=32, tolerance_hydrique=2, densite_plants_ha=143, debit_plant_lph=100),
]

PARCELLES = [  # nom, culture, m², sol, stade
    ("Parcelle F1", "Avocatier", 5000, "Limoneux", "Floraison"),
    ("Parcelle F2", "Palmier à huile", 8000, "Limoneux", "Fructification/Maturation"),
]


def appliquer(db: Session) -> list[str]:
    """Retourne ce qui a été créé (liste vide si déjà fait)."""
    if db.get(AjoutFait, IDENTIFIANT):
        return []
    cree = []
    for spec in PLANTES:
        if db.scalar(select(Plant.id).where(Plant.nom == spec["nom"])):
            continue                                       # existe déjà (créée par vos soins) : on la garde telle quelle
        spec = dict(spec)
        varietes = spec.pop("varietes")
        plant = Plant(**spec, source="seed")
        plant.varietes = [PlantVariety(nom=v) for v in varietes]
        db.add(plant)
        db.flush()
        db.add(PlantHistory(plant_id=plant.id, version=1, action="create", snapshot={k: getattr(plant, k) for k in PARAM_FIELDS}))
        cree.append(plant.nom)
    db.flush()
    plantes = {p.nom: p for p in db.scalars(select(Plant))}
    for nom, culture, surface, sol, stade in PARCELLES:
        if culture in plantes and not db.scalar(select(Parcelle.id).where(Parcelle.nom == nom)):
            p = plantes[culture]
            db.add(Parcelle(nom=nom, surface_m2=surface, type_sol=sol, plant_id=p.id, stade=stade, mesures=mesures_defaut(p)))
            cree.append(nom)
    db.add(AjoutFait(id=IDENTIFIANT))
    db.commit()
    return cree
