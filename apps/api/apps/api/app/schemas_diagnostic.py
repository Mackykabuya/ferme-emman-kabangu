from typing import Literal, Optional

from pydantic import BaseModel, Field


class DiagnosticRequest(BaseModel):
    plant_id: int
    type_sol: Literal["Sableux", "Limoneux", "Argileux"] = "Limoneux"
    ph: float = Field(ge=2, le=11, description="Acidité du sol")
    humidite_sol_pct: float = Field(ge=0, le=100)
    temperature_sol_c: float = Field(ge=-5, le=70)
    azote_N_mgkg: float = Field(ge=0, le=2000)
    phosphore_P_mgkg: float = Field(ge=0, le=2000)
    potassium_K_mgkg: float = Field(ge=0, le=5000)
    conductivite_ec_dsm: float = Field(ge=0, le=50, description="Quantité de sel dans le sol")
    surface_parcelle_m2: Optional[float] = Field(default=None, gt=0, le=50000,
                                                 description="Si fournie, les doses sont calculées pour la parcelle")


class DiagnosticResponse(BaseModel):
    plant_id: int
    plante: str
    params_version: int
    etat_sante: str
    etat_sante_libelle: str
    message_simple: str
    actions: list[str]
    a_surveiller: list[str]
    recommandation: str
    mode: Literal["ml", "regles"]
    confiance: Optional[float] = None
    probabilites: Optional[dict[str, float]] = None
    modele_version: Optional[str] = None
    plante_connue_du_modele: Optional[bool] = None
    avertissement: Optional[str] = None
