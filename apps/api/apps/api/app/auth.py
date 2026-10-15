"""
Comptes, rôles et sessions.

Rôles (du plus limité au plus puissant) :
  lecteur    : voit tout (parcelles, graphiques, alertes, eau), ne modifie rien
  operateur  : + ouvre/ferme les vannes, lance l'arrosage auto, saisit la météo, change le mode d'une parcelle
  agronome   : + gère le catalogue des plantes et les parcelles (création, culture, surface, suppression)
  admin      : + gère les comptes utilisateurs

Sessions : à la connexion le serveur remet un jeton aléatoire (valable SESSION_HEURES, 12 h par défaut). Seule son
empreinte SHA-256 est gardée en base : un vol de la base ne donne aucun jeton utilisable. Déconnexion = jeton supprimé.
Mots de passe : scrypt (bibliothèque standard), avec sel aléatoire. Aucun mot de passe n'est stocké en clair.
"""
import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models_auth import SessionAuth, Utilisateur

NIVEAUX = {"lecteur": 1, "operateur": 2, "agronome": 3, "admin": 4}
LIBELLES = {"lecteur": "lecteur", "operateur": "opérateur", "agronome": "agronome", "admin": "administrateur"}
SESSION_HEURES = float(os.getenv("SESSION_HEURES", "12"))
MDP_MIN = 8
_N, _R, _P = 2 ** 14, 8, 1


def _maintenant() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------- mots de passe ----------
def hacher(mdp: str) -> str:
    sel = os.urandom(16)
    h = hashlib.scrypt(mdp.encode(), salt=sel, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(sel).decode()}${base64.b64encode(h).decode()}"


def verifier(mdp: str, enregistre: str) -> bool:
    try:
        _, n, r, p, sel, h = enregistre.split("$")
        calc = hashlib.scrypt(mdp.encode(), salt=base64.b64decode(sel), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


FAUX_HASH = hacher(secrets.token_hex(8))     # comparé quand l'identifiant n'existe pas : même durée de réponse


def controler_mdp(mdp: str):
    if len(mdp) < MDP_MIN:
        raise HTTPException(422, f"Le mot de passe doit faire au moins {MDP_MIN} caractères.")


# ---------- jetons de session ----------
def _empreinte(jeton: str) -> str:
    return hashlib.sha256(jeton.encode()).hexdigest()


def ouvrir_session(db: Session, u: Utilisateur) -> tuple[str, datetime]:
    jeton = secrets.token_urlsafe(32)
    fin = _maintenant() + timedelta(hours=SESSION_HEURES)
    db.add(SessionAuth(empreinte=_empreinte(jeton), utilisateur_id=u.id, expire_le=fin))
    for vieille in db.scalars(select(SessionAuth).where(SessionAuth.expire_le < _maintenant())):
        db.delete(vieille)
    db.commit()
    return jeton, fin


def fermer_sessions(db: Session, utilisateur_id: int, sauf: str | None = None):
    for s in db.scalars(select(SessionAuth).where(SessionAuth.utilisateur_id == utilisateur_id)):
        if s.empreinte != sauf:
            db.delete(s)


# ---------- dépendances FastAPI ----------
_schema = HTTPBearer(auto_error=False, description="Collez ici le jeton reçu par POST /auth/connexion")


def jeton_courant(creds: HTTPAuthorizationCredentials | None = Depends(_schema)) -> str:
    if not creds:
        raise HTTPException(401, "Connexion requise.", headers={"WWW-Authenticate": "Bearer"})
    return creds.credentials


def utilisateur_courant(jeton: str = Depends(jeton_courant), db: Session = Depends(get_db)) -> Utilisateur:
    s = db.scalar(select(SessionAuth).where(SessionAuth.empreinte == _empreinte(jeton)))
    if not s or s.expire_le < _maintenant():
        raise HTTPException(401, "Session expirée ou invalide : reconnectez-vous.", headers={"WWW-Authenticate": "Bearer"})
    u = db.get(Utilisateur, s.utilisateur_id)
    if not u or not u.actif:
        raise HTTPException(401, "Ce compte est désactivé.", headers={"WWW-Authenticate": "Bearer"})
    return u


def exiger(role: str):
    """Dépendance : l'utilisateur connecté doit avoir au moins ce rôle."""
    def verif(u: Utilisateur = Depends(utilisateur_courant)) -> Utilisateur:
        if NIVEAUX[u.role] < NIVEAUX[role]:
            raise HTTPException(403, f"Droits insuffisants : cette action demande le rôle « {LIBELLES[role]} » "
                                     f"(votre rôle : {LIBELLES[u.role]}).")
        return u
    return verif


def a_le_role(u: Utilisateur, role: str) -> bool:
    return NIVEAUX[u.role] >= NIVEAUX[role]


# ---------- premier démarrage ----------
def creer_admin_initial(db: Session) -> tuple[str, str] | None:
    """S'il n'existe aucun compte, crée l'administrateur (ADMIN_IDENTIFIANT / ADMIN_MOT_DE_PASSE, sinon mot de passe
    aléatoire à lire dans le terminal). Retourne (identifiant, mot de passe) si un compte a été créé."""
    if db.scalar(select(Utilisateur.id).limit(1)):
        return None
    ident = os.getenv("ADMIN_IDENTIFIANT", "admin")
    mdp = os.getenv("ADMIN_MOT_DE_PASSE") or secrets.token_urlsafe(9)
    db.add(Utilisateur(identifiant=ident, nom="Responsable", role="admin", mdp_hash=hacher(mdp),
                       email=(os.getenv("ADMIN_EMAIL") or "").strip().lower() or None))
    db.commit()
    return ident, mdp


def email_admin_depuis_env(db: Session):
    """ADMIN_EMAIL donne son e-mail à l'administrateur déjà créé s'il n'en a pas encore (compte d'avant l'étape 19)."""
    mail = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    if not mail or db.scalar(select(Utilisateur.id).where(Utilisateur.email == mail)):
        return
    u = db.scalar(select(Utilisateur).where(Utilisateur.identifiant == os.getenv("ADMIN_IDENTIFIANT", "admin"), Utilisateur.email.is_(None)))
    if u:
        u.email = mail
        db.commit()
