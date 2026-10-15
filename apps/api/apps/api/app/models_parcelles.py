from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


_horloge: dict = {"simulee": None}


def maintenant() -> datetime:
    """Heure du système (UTC, sans fuseau). Pendant la simulation, c'est l'heure SIMULÉE : vannes, arrosages et
    mesures partagent ainsi la même chronologie, quelle que soit la vitesse de la simulation."""
    h = _horloge["simulee"]
    return h if h is not None else datetime.now(timezone.utc).replace(tzinfo=None)


class Parcelle(Base):
    __tablename__ = "parcelles"
    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(60), unique=True)
    surface_m2: Mapped[float]
    type_sol: Mapped[str] = mapped_column(String(12))
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"))
    stade: Mapped[str] = mapped_column(String(30))
    mode: Mapped[str] = mapped_column(String(10), default="auto")       # auto | manuel
    mesures: Mapped[dict] = mapped_column(JSON)                         # dernières mesures (simulées pour l'instant)
    vanne_fin: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    @property
    def vanne_ouverte(self) -> bool:
        return bool(self.vanne_fin and self.vanne_fin > maintenant())


class Arrosage(Base):
    __tablename__ = "arrosages"
    id: Mapped[int] = mapped_column(primary_key=True)
    parcelle_id: Mapped[int] = mapped_column(ForeignKey("parcelles.id"))
    action: Mapped[str] = mapped_column(String(10))                     # ouvrir | fermer
    minutes: Mapped[int]
    litres: Mapped[float]
    source: Mapped[str] = mapped_column(String(10))                     # manuel | auto
    at: Mapped[datetime] = mapped_column(DateTime, default=maintenant)


class Mesure(Base):
    """Historique des mesures d'une parcelle (alimente les graphiques)."""
    __tablename__ = "mesures"
    id: Mapped[int] = mapped_column(primary_key=True)
    parcelle_id: Mapped[int] = mapped_column(ForeignKey("parcelles.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=maintenant)
    mesures: Mapped[dict] = mapped_column(JSON)
    vanne_ouverte: Mapped[bool] = mapped_column(default=False)
