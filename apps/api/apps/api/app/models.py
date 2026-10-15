from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now():
    return datetime.now(timezone.utc)


class Plant(Base):
    __tablename__ = "plants"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(80), unique=True)
    categorie: Mapped[str] = mapped_column(String(60))
    # Coefficients culturaux Kc par stade
    kc_germination: Mapped[float]
    kc_vegetative: Mapped[float]
    kc_floraison: Mapped[float]
    kc_fructification: Mapped[float]
    # Chimie du sol (plages optimales)
    ph_min: Mapped[float]
    ph_max: Mapped[float]
    n_min: Mapped[float]
    n_max: Mapped[float]
    p_min: Mapped[float]
    p_max: Mapped[float]
    k_min: Mapped[float]
    k_max: Mapped[float]
    ec_max_dsm: Mapped[float]
    # Eau et température
    humidite_sol_min: Mapped[float]
    humidite_sol_max: Mapped[float]
    temp_opt_min: Mapped[float]
    temp_opt_max: Mapped[float]
    tolerance_hydrique: Mapped[int]
    # Conduite culturale
    densite_plants_ha: Mapped[int]
    debit_plant_lph: Mapped[float]
    # Gouvernance
    params_version: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(default=True)
    source: Mapped[str] = mapped_column(String(10), default="user")  # seed | user | learned
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    varietes: Mapped[list["PlantVariety"]] = relationship(
        back_populates="plant", cascade="all, delete-orphan", order_by="PlantVariety.nom"
    )


class PlantVariety(Base):
    __tablename__ = "plant_varieties"
    __table_args__ = (UniqueConstraint("plant_id", "nom"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id", ondelete="CASCADE"))
    nom: Mapped[str] = mapped_column(String(80))
    plant: Mapped[Plant] = relationship(back_populates="varietes")


class PlantHistory(Base):
    """Audit : instantané complet des paramètres à chaque version."""
    __tablename__ = "plant_param_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id", ondelete="CASCADE"))
    version: Mapped[int]
    action: Mapped[str] = mapped_column(String(20))  # create | update | deactivate | reactivate
    snapshot: Mapped[dict] = mapped_column(JSON)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
