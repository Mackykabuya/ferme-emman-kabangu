"""Charge le catalogue généré par ml/generate_datasets.py au premier démarrage."""
import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Plant, PlantHistory, PlantVariety
from .schemas import PARAM_FIELDS

# apps/api/app/seed.py -> racine du projet = parents[3]
CATALOGUE_PATH = Path(__file__).resolve().parents[3] / "ml" / "data" / "catalogue_plantes.json"


def _convert(c: dict) -> dict:
    kc = c["kc"]
    out = {k: c[k] for k in (
        "categorie", "ph_min", "ph_max", "n_min", "n_max", "p_min", "p_max", "k_min", "k_max",
        "ec_max_dsm", "humidite_sol_min", "humidite_sol_max", "temp_opt_min", "temp_opt_max",
        "densite_plants_ha", "debit_plant_lph")}
    out.update(
        nom=c["nom"], tolerance_hydrique=c["tolerance_hydrique"],
        kc_germination=kc["germination"], kc_vegetative=kc["vegetative"],
        kc_floraison=kc["floraison"], kc_fructification=kc["fructification"])
    return out


def seed_catalogue(db: Session, path: Path = CATALOGUE_PATH) -> int:
    """Retourne le nombre de plantes insérées (0 si la table est déjà remplie ou le fichier absent)."""
    if db.scalar(select(func.count(Plant.id))) or not Path(path).exists():
        return 0
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    for c in items:
        plant = Plant(**_convert(c), source="seed")
        plant.varietes = [PlantVariety(nom=v) for v in c["varietes"]]
        db.add(plant)
        db.flush()
        db.add(PlantHistory(plant_id=plant.id, version=1, action="create",
                            snapshot={k: getattr(plant, k) for k in PARAM_FIELDS}))
    db.commit()
    return len(items)
