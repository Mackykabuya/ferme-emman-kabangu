from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..engine.anomalies import analyser_parcelle
from ..models import Plant
from ..models_parcelles import Parcelle
from .parcelles import DEBIT_POMPE_LH, historique_mesures

router = APIRouter(prefix="/alertes", tags=["Alertes et anomalies"])
ORDRE = {"critique": 0, "attention": 1, "info": 2}


def toutes_les_alertes(db: Session) -> list[dict]:
    sortie = []
    for p in db.scalars(select(Parcelle).order_by(Parcelle.nom)):
        plant = db.get(Plant, p.plant_id)
        besoin = plant.debit_plant_lph * p.surface_m2 * plant.densite_plants_ha / 10000
        for a in analyser_parcelle(p.nom, historique_mesures(db, p.id, 18), besoin, DEBIT_POMPE_LH):
            sortie.append({**a, "parcelle_id": p.id})
    return sorted(sortie, key=lambda a: (ORDRE[a["gravite"]], a["parcelle"]))


@router.get("")
def alertes(db: Session = Depends(get_db)):
    """Anomalies détectées en ce moment sur la ferme (capteur muet ou faux, vanne qui n'arrose pas, pompe trop faible)."""
    liste = toutes_les_alertes(db)
    return {"total": len(liste), "urgentes": sum(a["gravite"] != "info" for a in liste), "alertes": liste}
