from typing import Literal

from pydantic import BaseModel, Field

from .schemas_diagnostic import DiagnosticResponse
from .schemas_irrigation import IrrigationResponse, Stade


class DecisionRequest(BaseModel):
    plant_id: int
    stade: Stade
    type_sol: Literal["Sableux", "Limoneux", "Argileux"] = "Limoneux"
    surface_parcelle_m2: float = Field(default=1000, gt=0, le=50000)
    # Mesures du sol
    ph: float = Field(ge=2, le=11)
    humidite_sol_pct: float = Field(ge=0, le=100)
    temperature_sol_c: float = Field(ge=-5, le=70)
    azote_N_mgkg: float = Field(ge=0, le=2000)
    phosphore_P_mgkg: float = Field(ge=0, le=2000)
    potassium_K_mgkg: float = Field(ge=0, le=5000)
    conductivite_ec_dsm: float = Field(ge=0, le=50)
    # Air et météo
    temperature_air_c: float = Field(ge=-5, le=55)
    humidite_air_pct: float = Field(ge=0, le=100)
    prevision_pluie_6h_mm: float = Field(default=0, ge=0, le=300)


class DecisionResponse(BaseModel):
    ordre: list[str]
    etape_1_diagnostic: DiagnosticResponse
    etape_2_irrigation: IrrigationResponse
    resume_agriculteur: str
