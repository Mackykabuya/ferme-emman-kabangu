from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..engine.irrigation import estimer_irrigation, fonction_prediction
from ..models import Plant
from ..schemas_irrigation import IrrigationRequest, IrrigationResponse
from .diagnostic import plante_active_ou_erreur

router = APIRouter(prefix="/irrigation", tags=["Irrigation"])


def reponse_irrigation(plant: Plant, stade: str, decision) -> IrrigationResponse:
    return IrrigationResponse(plant_id=plant.id, plante=plant.nom, params_version=plant.params_version,
                              stade=stade, **asdict(decision))


@router.post("/recommandation", response_model=IrrigationResponse)
def recommandation(req: IrrigationRequest, db: Session = Depends(get_db)):
    """Calcul seul. Pour tenir compte du diagnostic du sol, préférez POST /decision/parcelle."""
    plant = plante_active_ou_erreur(db, req.plant_id)
    d = estimer_irrigation(plant, req.stade, req.temperature_air_c, req.humidite_air_pct, req.humidite_sol_pct,
                           req.type_sol, req.prevision_pluie_6h_mm, req.surface_parcelle_m2,
                           etat_sante=req.etat_sante, salinite_elevee=req.salinite_elevee,
                           predire_ratio=fonction_prediction())
    return reponse_irrigation(plant, req.stade, d)
