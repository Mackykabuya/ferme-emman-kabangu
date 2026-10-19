from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, true
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
    notif_alertes: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())     # reçoit les alertes par e-mail
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


class AlerteNotifiee(Base):
    """Alertes déjà annoncées par e-mail : évite de renvoyer le même message à chaque vérification."""
    __tablename__ = "alertes_notifiees"
    cle: Mapped[str] = mapped_column(String(80), primary_key=True)           # « code:parcelle_id »
    notifiee_le: Mapped[datetime] = mapped_column(DateTime, default=_maintenant)


class JournalAction(Base):
    """Journal des actions : qui a fait quoi, sur quoi, et quand (heure réelle, UTC). Les mots de passe n'y figurent jamais."""
    __tablename__ = "journal_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=_maintenant, index=True)
    utilisateur_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    utilisateur: Mapped[str] = mapped_column(String(60), default="")          # identifiant au moment de l'action (reste lisible si le compte est supprimé)
    role: Mapped[str] = mapped_column(String(12), default="")
    action: Mapped[str] = mapped_column(String(80))
    cible: Mapped[str] = mapped_column(String(120), default="")
    detail: Mapped[str] = mapped_column(String(300), default="")
    ip: Mapped[str] = mapped_column(String(45), default="")
