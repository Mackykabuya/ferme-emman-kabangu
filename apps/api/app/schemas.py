from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator


class PlantBase(BaseModel):
    nom: str = Field(min_length=2, max_length=80)
    categorie: str = Field(min_length=2, max_length=60)
    kc_germination: float = Field(ge=0.1, le=1.5)
    kc_vegetative: float = Field(ge=0.1, le=1.5)
    kc_floraison: float = Field(ge=0.1, le=1.5)
    kc_fructification: float = Field(ge=0.1, le=1.5)
    ph_min: float = Field(ge=3, le=10)
    ph_max: float = Field(ge=3, le=10)
    n_min: float = Field(gt=0)
    n_max: float = Field(gt=0)
    p_min: float = Field(gt=0)
    p_max: float = Field(gt=0)
    k_min: float = Field(gt=0)
    k_max: float = Field(gt=0)
    ec_max_dsm: float = Field(gt=0, le=20)
    humidite_sol_min: float = Field(ge=0, le=100)
    humidite_sol_max: float = Field(ge=0, le=100)
    temp_opt_min: float = Field(ge=0, le=50)
    temp_opt_max: float = Field(ge=0, le=50)
    tolerance_hydrique: int = Field(ge=1, le=5, description="1 = très sensible à la sécheresse, 5 = très tolérante")
    densite_plants_ha: int = Field(gt=0)
    debit_plant_lph: float = Field(gt=0, description="Débit d'irrigation par plant (L/h)")

    @model_validator(mode="after")
    def _plages_coherentes(self):
        for nom in ("ph", "n", "p", "k", "humidite_sol", "temp_opt"):
            if getattr(self, f"{nom}_min") >= getattr(self, f"{nom}_max"):
                raise ValueError(f"{nom}_min doit être strictement inférieur à {nom}_max")
        return self


PARAM_FIELDS = list(PlantBase.model_fields)


class PlantCreate(PlantBase):
    varietes: list[str] = Field(default_factory=list)


# Mise à jour partielle : tous les champs optionnels, la cohérence est revalidée après fusion.
PlantUpdate = create_model(
    "PlantUpdate",
    __config__=ConfigDict(extra="forbid"),
    **{n: (Optional[f.annotation], None) for n, f in PlantBase.model_fields.items()},
)


class VarietyIn(BaseModel):
    nom: str = Field(min_length=2, max_length=80)


class VarietyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nom: str


class PlantOut(PlantBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    params_version: int
    is_active: bool
    source: str
    created_at: datetime
    updated_at: datetime
    varietes: list[VarietyOut]


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    version: int
    action: str
    snapshot: dict
    changed_at: datetime
