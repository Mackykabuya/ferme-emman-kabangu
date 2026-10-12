from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..engine.diagnostic import diagnostiquer
from ..models import Plant
from ..schemas_diagnostic import DiagnosticRequest, DiagnosticResponse

router = APIRouter(prefix="/diagnostic", tags=["Diagnostic pédologique"])


def plante_active_ou_erreur(db: Session, plant_id: int) -> Plant:
    plant = db.get(Plant, plant_id)
    if not plant:
        raise HTTPException(404, "Plante introuvable")
    if not plant.is_active:
        raise HTTPException(409, "Cette plante est désactivée dans le catalogue")
    return plant


def mesures_sol(req) -> dict:
    return {"ph": req.ph, "humidite_sol": req.humidite_sol_pct, "temperature_sol": req.temperature_sol_c,
            "N": req.azote_N_mgkg, "P": req.phosphore_P_mgkg, "K": req.potassium_K_mgkg,
            "ec": req.conductivite_ec_dsm, "type_sol": req.type_sol}


def reponse_diagnostic(plant: Plant, resultat: dict) -> DiagnosticResponse:
    return DiagnosticResponse(plant_id=plant.id, plante=plant.nom, params_version=plant.params_version, **resultat)


@router.post("/pedologique", response_model=DiagnosticResponse)
def diagnostic_pedologique(req: DiagnosticRequest, db: Session = Depends(get_db)):
    plant = plante_active_ou_erreur(db, req.plant_id)
    return reponse_diagnostic(plant, diagnostiquer(plant, mesures_sol(req), req.surface_parcelle_m2))
