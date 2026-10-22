from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from sqlalchemy.orm import Session

from .. import courriel, journal, notifications, sauvegarde
from ..auth import exiger, utilisateur_courant
from ..database import get_db
from ..engine import eau as moteur_eau

router = APIRouter(prefix="/admin", tags=["Administration"], dependencies=[Depends(exiger("admin"))])


@router.get("/sauvegardes")
def liste():
    """Sauvegardes de la base (les plus récentes d'abord) et réglages automatiques."""
    return {"sauvegardes": sauvegarde.lister(), "toutes_les_heures": sauvegarde.HEURES, "conservees": sauvegarde.GARDER}


@router.post("/sauvegardes", status_code=201)
def creer():
    try:
        return sauvegarde.sauvegarder()
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.get("/sauvegardes/{nom}")
def telecharger(nom: str):
    p = sauvegarde.chemin(nom)
    if not p:
        raise HTTPException(404, "Sauvegarde introuvable.")
    return FileResponse(p, filename=p.name, media_type="application/octet-stream")


@router.post("/test-courriel")
def test_courriel(u=Depends(utilisateur_courant)):
    """Envoie un e-mail d'essai à l'adresse de l'administrateur connecté (vérifie les réglages SMTP)."""
    if not u.email:
        raise HTTPException(409, "Votre compte n'a pas d'adresse e-mail : ajoutez-la dans « Mon compte ».")
    if not courriel.configure():
        raise HTTPException(409, "L'envoi d'e-mails n'est pas réglé sur ce serveur (ni SMTP_HOTE ni EMAIL_API dans les réglages).")
    if not courriel.envoyer(u.email, "Ferme Emman Kabangu : e-mail de test",
                            "Bonjour,\n\nSi vous lisez ce message, l'envoi d'e-mails de la ferme fonctionne.\n"
                            "Les alertes seront envoyées aux comptes actifs ayant une adresse e-mail et un rôle "
                            f"« {notifications.ROLE_MIN} » ou plus, toutes les {notifications.MINUTES:g} minutes si besoin."):
        raise HTTPException(502, "L'envoi a échoué : vérifiez les réglages SMTP_* ou EMAIL_API* (détail dans le journal du serveur).")
    return {"envoye_a": u.email}


@router.get("/journal")
def lire_journal(jours: int | None = Query(None, ge=1, le=3650), utilisateur: str = Query("", max_length=60), q: str = Query("", max_length=80),
                 limite: int = Query(100, ge=1, le=500), debut: int = Query(0, ge=0), db: Session = Depends(get_db)):
    """Journal des actions (administrateur) : les plus récentes d'abord. Filtres : période en jours, compte, mot recherché."""
    total, lignes = journal.lister(db, jours, utilisateur.strip(), q.strip(), limite, debut)
    from datetime import timezone
    tz = moteur_eau.fuseau()
    return {"total": total, "actions": [
        {"id": j.id, "quand": j.at.replace(tzinfo=timezone.utc).astimezone(tz).strftime("%d/%m/%Y %H:%M:%S"), "utilisateur": j.utilisateur,
         "role": j.role, "action": j.action, "cible": j.cible, "detail": j.detail, "ip": j.ip} for j in lignes]}
