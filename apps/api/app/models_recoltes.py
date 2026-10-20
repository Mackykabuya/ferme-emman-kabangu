from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models_auth import _maintenant


class Campagne(Base):
    """Un cycle de culture sur une parcelle : du semis (ou de la plantation) à la fin des récoltes."""
    __tablename__ = "campagnes"
    id: Mapped[int] = mapped_column(primary_key=True)
    parcelle_id: Mapped[int] = mapped_column(ForeignKey("parcelles.id"), index=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"))
    semis_le: Mapped[date] = mapped_column(Date)
    recolte_prevue_le: Mapped[date | None] = mapped_column(Date, default=None)
    terminee_le: Mapped[date | None] = mapped_column(Date, default=None)       # vide = en cours
    note: Mapped[str] = mapped_column(String(200), default="")
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=_maintenant)


class Recolte(Base):
    __tablename__ = "recoltes"
    id: Mapped[int] = mapped_column(primary_key=True)
    campagne_id: Mapped[int] = mapped_column(ForeignKey("campagnes.id"), index=True)
    parcelle_id: Mapped[int] = mapped_column(ForeignKey("parcelles.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    quantite_kg: Mapped[float] = mapped_column(Float)
    qualite: Mapped[str] = mapped_column(String(1), default="B")                # A (très bonne) | B | C (déclassée)
    surface_m2: Mapped[float] = mapped_column(Float)                           # surface de la parcelle à ce moment (le rendement reste juste si elle change)
    note: Mapped[str] = mapped_column(String(200), default="")
    saisi_par: Mapped[str] = mapped_column(String(40), default="")
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=_maintenant)
