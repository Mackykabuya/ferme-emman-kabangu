from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import courriel, notifications, sauvegarde
from ..auth import exiger, utilisateur_courant

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
        raise HTTPException(409, "L'envoi d'e-mails n'est pas réglé sur ce serveur (SMTP_HOTE absent du fichier .env).")
    if not courriel.envoyer(u.email, "Ferme Emman Kabangu : e-mail de test",
                            "Bonjour,\n\nSi vous lisez ce message, l'envoi d'e-mails de la ferme fonctionne.\n"
                            "Les alertes seront envoyées aux comptes actifs ayant une adresse e-mail et un rôle "
                            f"« {notifications.ROLE_MIN} » ou plus, toutes les {notifications.MINUTES:g} minutes si besoin."):
        raise HTTPException(502, "L'envoi a échoué : vérifiez SMTP_* dans le fichier .env (détail dans le journal du serveur).")
    return {"envoye_a": u.email}
