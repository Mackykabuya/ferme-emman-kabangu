from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import exiger
from ..database import get_db
from ..models_parcelles import Parcelle

from .. import simulation

router = APIRouter(prefix="/simulation", tags=["Simulation des capteurs"])


def _etat() -> dict:
    h = simulation.ETAT["horloge"]
    dispo = simulation.SECONDES > 0
    return {"disponible": dispo, "active": simulation.actif(), "heure_simulee": h.isoformat() if h else None,
            "minutes_par_pas": simulation.PAS_MIN, "secondes_par_pas": simulation.SECONDES,
            "pannes": dict(simulation.PANNES), "acceleration": round(simulation.PAS_MIN * 60 / simulation.SECONDES) if dispo else None}


@router.get("")
def etat():
    return _etat()


@router.post("/pause", dependencies=[Depends(exiger("operateur"))])
def pause():
    simulation.ETAT["actif"] = False
    return _etat()


@router.post("/reprendre", dependencies=[Depends(exiger("operateur"))])
def reprendre():
    if simulation.SECONDES <= 0:
        raise HTTPException(409, "La simulation est désactivée (SIMULATION_SECONDES=0).")
    simulation.ETAT["actif"] = True
    return _etat()


class PanneIn(BaseModel):
    parcelle_id: int
    type: Literal["bloque", "aberrant", "vanne"]


@router.post("/panne", dependencies=[Depends(exiger("operateur"))])
def provoquer_panne(req: PanneIn, db: Session = Depends(get_db)):
    """Provoque une panne simulée pour voir les alertes : capteur « bloque » (valeur figée), « aberrant » (valeur
    impossible) ou « vanne » (ouverte mais l'eau n'arrive pas)."""
    if simulation.SECONDES <= 0:
        raise HTTPException(409, "La simulation est désactivée (SIMULATION_SECONDES=0).")
    if not db.get(Parcelle, req.parcelle_id):
        raise HTTPException(404, "Parcelle introuvable")
    simulation.PANNES[req.parcelle_id] = req.type
    return _etat()


@router.delete("/panne/{pid}", dependencies=[Depends(exiger("operateur"))])
def reparer(pid: int):
    simulation.PANNES.pop(pid, None)
    return _etat()
