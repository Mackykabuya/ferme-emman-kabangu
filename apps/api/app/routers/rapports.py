from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from .. import rapports
from ..database import get_db

router = APIRouter(prefix="/rapports", tags=["Rapports"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _fabriquer(fabrique, d: dict) -> bytes:
    try:
        return fabrique(d)
    except ImportError as e:                       # module non installé sur ce serveur
        raise HTTPException(503, f"Module manquant ({e.name}) : lancez « pip install -r apps/api/requirements.txt » puis relancez le serveur.")


def _envoyer(contenu: bytes, d: dict, ext: str, media: str) -> Response:
    return Response(contenu, media_type=media, headers={"Content-Disposition": f'attachment; filename="{rapports.nom_fichier(d, ext)}"'})


@router.get("/ferme.pdf")
def pdf(jours: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    """Rapport PDF : eau consommée, journal des arrosages, alertes, état des parcelles."""
    d = rapports.donnees(db, jours)
    return _envoyer(_fabriquer(rapports.en_pdf, d), d, "pdf", "application/pdf")


@router.get("/ferme.xlsx")
def xlsx(jours: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    """Même rapport en classeur Excel (une feuille par sujet), pour trier, filtrer ou calculer."""
    d = rapports.donnees(db, jours)
    return _envoyer(_fabriquer(rapports.en_xlsx, d), d, "xlsx", XLSX)
