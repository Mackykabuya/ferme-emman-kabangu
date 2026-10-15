from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _maintenant() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Utilisateur(Base):
    __tablename__ = "utilisateurs"
    id: Mapped[int] = mapped_column(primary_key=True)
    identifiant: Mapped[str] = mapped_column(String(40), unique=True)
    nom: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(12))                    # lecteur | operateur | agronome | admin
    mdp_hash: Mapped[str] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)        # en minuscules
    actif: Mapped[bool] = mapped_column(default=True)
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=_maintenant)


class SessionAuth(Base):
    __tablename__ = "sessions_auth"
    id: Mapped[int] = mapped_column(primary_key=True)
    empreinte: Mapped[str] = mapped_column(String(64), unique=True, index=True)     # SHA-256 du jeton
    utilisateur_id: Mapped[int] = mapped_column(ForeignKey("utilisateurs.id"), index=True)
    expire_le: Mapped[datetime] = mapped_column(DateTime)


class DemandeInscription(Base):
    """Demande de compte faite depuis la page publique : n'ouvre aucun accès tant qu'un administrateur ne l'a pas acceptée."""
    __tablename__ = "demandes_inscription"
    id: Mapped[int] = mapped_column(primary_key=True)
    identifiant: Mapped[str] = mapped_column(String(40), unique=True)
    nom: Mapped[str] = mapped_column(String(80))
    mdp_hash: Mapped[str] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=_maintenant)


class ReinitialisationMdp(Base):
    """Jeton à usage unique pour choisir un nouveau mot de passe (seule l'empreinte est stockée)."""
    __tablename__ = "reinitialisations_mdp"
    id: Mapped[int] = mapped_column(primary_key=True)
    empreinte: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    utilisateur_id: Mapped[int] = mapped_column(ForeignKey("utilisateurs.id"), index=True)
    expire_le: Mapped[datetime] = mapped_column(DateTime)
    cree_le: Mapped[datetime] = mapped_column(DateTime, default=_maintenant)
