from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..engine import eau
from ..engine.irrigation import STADES
from ..models import Plant
from ..models_parcelles import Arrosage, Mesure, Parcelle, maintenant

router = APIRouter(prefix="/eau", tags=["Suivi de l'eau"])


@router.get("")
def consommation(jours: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    """Eau réellement envoyée aux parcelles sur les N derniers jours, comparée à un arrosage classique (voir `methode`).
    La période commence au plus tôt à la première donnée enregistrée : pas d'économie « inventée » avant le démarrage."""
    fin = maintenant()
    premier = min((d for d in (db.scalar(select(func.min(Mesure.at))), db.scalar(select(func.min(Arrosage.at)))) if d), default=fin)
    debut = max(fin - timedelta(days=jours), premier)
    parcelles = []
    for p in db.scalars(select(Parcelle)):
        plant = db.get(Plant, p.plant_id)
        parcelles.append({"id": p.id, "nom": p.nom, "surface_m2": p.surface_m2, "kc": float(getattr(plant, STADES[p.stade]))})
    arr = [{"parcelle_id": a.parcelle_id, "action": a.action, "minutes": a.minutes, "litres": a.litres, "at": a.at}
           for a in db.scalars(select(Arrosage).where(Arrosage.at >= debut - timedelta(hours=3), Arrosage.at <= fin))]
    return eau.bilan(parcelles, arr, debut, fin)
