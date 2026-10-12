from typing import Literal, Optional

from pydantic import BaseModel, Field

Stade = Literal["Germination", "Croissance végétative", "Floraison", "Fructification/Maturation"]
Etat = Literal["Saine", "Carence en N", "Carence en P", "Carence en K", "Stress thermique",
               "Attaque Fongique/Parasitaire"]


class IrrigationRequest(BaseModel):
    plant_id: int
    stade: Stade
    temperature_air_c: float = Field(ge=-5, le=55)
    humidite_air_pct: float = Field(ge=0, le=100)
    humidite_sol_pct: float = Field(ge=0, le=100)
    type_sol: Literal["Sableux", "Limoneux", "Argileux"] = "Limoneux"
    prevision_pluie_6h_mm: float = Field(default=0, ge=0, le=300)
    surface_parcelle_m2: float = Field(default=1000, gt=0, le=50000)
    etat_sante: Etat = Field(default="Saine", description="Résultat du diagnostic du sol, s'il est connu")
    salinite_elevee: bool = False


class IrrigationResponse(BaseModel):
    plant_id: int
    plante: str
    params_version: int          # version des paramètres de la plante utilisée pour ce calcul
    stade: Stade
    et0_mm_jour: float
    kc: float
    nb_plants: int
    besoin_L_par_plant_jour: float
    besoin_L_parcelle_jour: float
    vanne_ouverte: bool
    duree_min: int
    code_decision: Literal["irrigation", "pluie_legere", "pluie_forte", "sol_humide"]
    motif: str
    resume: str
    conseil_horaire: str
    ajustement: Optional[str] = None
    methode: str
