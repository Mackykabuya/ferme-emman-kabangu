"""Journal des actions : qui a ouvert quelle vanne, créé quel compte, modifié quelle parcelle, et quand.

Les routes d'écriture (POST/PUT/DELETE) réussies sont notées automatiquement par un intergiciel (voir main.py) ; les
connexions (réussies ou refusées) le sont dans routers/auth.py. Une route peut préciser l'action en renseignant
`request.state.journal_cible` / `journal_detail`, ou l'ignorer avec `request.state.journal_ignorer = True`
(les mesures envoyées par un capteur, par exemple, rempliraient le journal pour rien).
Jamais de mot de passe, de jeton ni de corps de requête : seulement des libellés."""
import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .models import Plant
from .models_auth import JournalAction, Utilisateur
from .models_parcelles import Parcelle

MAX_LIGNES = int(os.getenv("JOURNAL_MAX", "20000"))

# (méthode, chemin) -> libellé. Les routes absentes de cette liste (lectures, analyses, préférences) ne sont pas notées.
REGLES = [
    ("POST", r"/auth/mot-de-passe", "Mot de passe changé"),
    ("PUT", r"/auth/moi/email", "Adresse e-mail modifiée"),
    ("POST", r"/auth/utilisateurs/\d+/lien-reinitialisation", "Lien de réinitialisation généré"),
    ("POST", r"/auth/moi/2fa/activer", "Double authentification activée"),
    ("POST", r"/auth/moi/2fa/desactiver", "Double authentification désactivée"),
    ("POST", r"/auth/moi/2fa/codes-secours", "Codes de secours renouvelés"),
    ("DELETE", r"/auth/utilisateurs/\d+/2fa", "Double authentification réinitialisée"),
    ("POST", r"/auth/utilisateurs", "Compte créé"),
    ("PUT", r"/auth/utilisateurs/\d+", "Compte modifié"),
    ("POST", r"/auth/inscription", "Demande d'inscription"),
    ("POST", r"/auth/demandes/\d+/accepter", "Inscription acceptée"),
    ("DELETE", r"/auth/demandes/\d+", "Inscription refusée"),
    ("POST", r"/auth/mot-de-passe-oublie", "Mot de passe oublié (demande)"),
    ("POST", r"/auth/reinitialiser", "Mot de passe réinitialisé"),
    ("PUT", r"/meteo", "Météo saisie à la main"),
    ("POST", r"/meteo/actualiser", "Météo réelle récupérée"),
    ("POST", r"/recoltes/campagnes", "Campagne ouverte"),
    ("PUT", r"/recoltes/campagnes/\d+", "Campagne modifiée"),
    ("DELETE", r"/recoltes/campagnes/\d+", "Campagne supprimée"),
    ("POST", r"/recoltes", "Récolte enregistrée"),
    ("DELETE", r"/recoltes/\d+", "Récolte supprimée"),
    ("POST", r"/parcelles/appliquer-auto", "Arrosage automatique lancé"),
    ("POST", r"/parcelles", "Parcelle créée"),
    ("POST", r"/parcelles/\d+/vanne", "Vanne"),
    ("PUT", r"/parcelles/\d+", "Parcelle modifiée"),
    ("DELETE", r"/parcelles/\d+", "Parcelle supprimée"),
    ("POST", r"/plants", "Plante ajoutée au catalogue"),
    ("POST", r"/plants/\d+/reactivate", "Plante réactivée"),
    ("POST", r"/plants/\d+/varietes", "Variété ajoutée"),
    ("DELETE", r"/plants/\d+/varietes/\d+", "Variété retirée"),
    ("PUT", r"/plants/\d+", "Plante modifiée"),
    ("DELETE", r"/plants/\d+", "Plante désactivée"),
    ("POST", r"/simulation/pause", "Simulation mise en pause"),
    ("POST", r"/simulation/reprendre", "Simulation reprise"),
    ("POST", r"/simulation/panne", "Panne simulée"),
    ("DELETE", r"/simulation/panne/\d+", "Panne simulée réparée"),
    ("POST", r"/simulation/reinitialiser", "Simulation remise à la date du jour"),
    ("POST", r"/admin/sauvegardes", "Sauvegarde de la base créée"),
    ("POST", r"/admin/test-courriel", "E-mail de test envoyé"),
]
_REGLES = [(m, re.compile(rf"^{p}$"), lib) for m, p, lib in REGLES]
_CIBLES = [(re.compile(r"^/parcelles/(\d+)"), Parcelle, "nom"), (re.compile(r"^/simulation/panne/(\d+)$"), Parcelle, "nom"),
           (re.compile(r"^/plants/(\d+)"), Plant, "nom"), (re.compile(r"^/auth/utilisateurs/(\d+)"), Utilisateur, "identifiant")]


def libelle(methode: str, chemin: str) -> str | None:
    chemin = chemin.rstrip("/") or "/"
    return next((lib for m, motif, lib in _REGLES if m == methode and motif.match(chemin)), None)


def noter(db: Session, utilisateur: Utilisateur | None, action: str, cible: str = "", detail: str = "", ip: str = "", visiteur: str = "") -> None:
    db.add(JournalAction(utilisateur_id=utilisateur.id if utilisateur else None, utilisateur=(utilisateur.identifiant if utilisateur else visiteur or "visiteur")[:60],
                         role=utilisateur.role if utilisateur else "", action=action[:80], cible=cible[:120], detail=detail[:300], ip=ip[:45]))
    db.commit()
    if MAX_LIGNES > 0 and (db.scalar(select(func.max(JournalAction.id))) or 0) % 500 == 0:          # de temps en temps : on garde les plus récentes
        seuil = db.scalar(select(JournalAction.id).order_by(JournalAction.id.desc()).offset(MAX_LIGNES).limit(1))
        if seuil:
            db.execute(delete(JournalAction).where(JournalAction.id <= seuil))
            db.commit()


def adresse_ip(request) -> str:
    """Adresse de l'appelant (derrière le proxy Caddy : première adresse de X-Forwarded-For)."""
    pour = request.headers.get("x-forwarded-for", "")
    return (pour.split(",")[0].strip() if pour else (request.client.host if request.client else ""))


def enregistrer(db: Session, request, statut: int) -> None:
    """Appelé après chaque requête : note les écritures réussies."""
    if request.method not in ("POST", "PUT", "DELETE") or statut >= 400:
        return
    st = request.state
    chemin = request.url.path
    lib = libelle(request.method, chemin)
    if not lib or getattr(st, "journal_ignorer", False):
        return
    cible = getattr(st, "journal_cible", "")
    if not cible:
        for motif, modele, champ in _CIBLES:
            m = motif.match(chemin)
            if m and (obj := db.get(modele, int(m.group(1)))):
                cible = str(getattr(obj, champ))
                break
    detail = getattr(st, "journal_detail", "")
    if lib == "Vanne":
        lib = "Vanne " + ("ouverte" if "ouverte" in detail else "fermée")
    noter(db, getattr(st, "utilisateur", None), lib, cible, detail, adresse_ip(request))


def lister(db: Session, jours: int | None, utilisateur: str, q: str, limite: int, debut: int):
    cond = []
    if jours:
        cond.append(JournalAction.at >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=jours))
    if utilisateur:
        cond.append(JournalAction.utilisateur == utilisateur)
    if q:
        cond.append(func.lower(JournalAction.action + " " + JournalAction.cible + " " + JournalAction.detail).contains(q.lower()))
    total = db.scalar(select(func.count()).select_from(JournalAction).where(*cond))
    lignes = db.scalars(select(JournalAction).where(*cond).order_by(JournalAction.id.desc()).offset(debut).limit(limite)).all()
    return total, lignes
