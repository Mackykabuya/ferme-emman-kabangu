from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import sauvegarde
from ..auth import exiger

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
