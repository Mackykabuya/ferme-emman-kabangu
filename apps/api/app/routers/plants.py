import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import exiger
from ..database import get_db
from ..models import Plant, PlantHistory, PlantVariety
from ..schemas import (PARAM_FIELDS, HistoryOut, PlantBase, PlantCreate, PlantOut,
                       PlantUpdate, VarietyIn)

router = APIRouter(prefix="/plants", tags=["Catalogue végétal"])


def _get_or_404(db: Session, plant_id: int) -> Plant:
    plant = db.get(Plant, plant_id)
    if not plant:
        raise HTTPException(404, "Plante introuvable")
    return plant


def _log(db: Session, plant: Plant, action: str):
    snapshot = {k: getattr(plant, k) for k in PARAM_FIELDS}
    db.add(PlantHistory(plant_id=plant.id, version=plant.params_version, action=action, snapshot=snapshot))


def _name_taken(db: Session, nom: str, exclude_id: int | None = None) -> bool:
    q = select(Plant.id).where(Plant.nom == nom)
    if exclude_id:
        q = q.where(Plant.id != exclude_id)
    return db.scalar(q) is not None


@router.get("", response_model=list[PlantOut])
def list_plants(include_inactive: bool = False, categorie: str | None = None,
                db: Session = Depends(get_db)):
    q = select(Plant).order_by(Plant.nom)
    if not include_inactive:
        q = q.where(Plant.is_active.is_(True))
    if categorie:
        q = q.where(Plant.categorie == categorie)
    return db.scalars(q).all()


@router.get("/{plant_id}", response_model=PlantOut)
def get_plant(plant_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, plant_id)


@router.post("", response_model=PlantOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(exiger("agronome"))])
def create_plant(payload: PlantCreate, db: Session = Depends(get_db)):
    if _name_taken(db, payload.nom):
        raise HTTPException(409, f"Une plante nommée « {payload.nom} » existe déjà")
    data = payload.model_dump(exclude={"varietes"})
    plant = Plant(**data, source="user")
    plant.varietes = [PlantVariety(nom=n) for n in dict.fromkeys(payload.varietes)]
    db.add(plant)
    db.flush()
    _log(db, plant, "create")
    db.commit()
    return plant


@router.put("/{plant_id}", response_model=PlantOut, dependencies=[Depends(exiger("agronome"))])
def update_plant(plant_id: int, payload: PlantUpdate, db: Session = Depends(get_db)):
    plant = _get_or_404(db, plant_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "Aucun champ à modifier")
    merged = {**{k: getattr(plant, k) for k in PARAM_FIELDS}, **changes}
    try:  # on revalide l'ensemble : une modification ne doit jamais rendre la plante incohérente
        valid = PlantBase.model_validate(merged)
    except ValidationError as e:
        raise HTTPException(422, json.loads(e.json()))
    if "nom" in changes and _name_taken(db, valid.nom, exclude_id=plant.id):
        raise HTTPException(409, f"Une plante nommée « {valid.nom} » existe déjà")
    for k in changes:
        setattr(plant, k, getattr(valid, k))
    plant.params_version += 1
    _log(db, plant, "update")
    db.commit()
    return plant


@router.delete("/{plant_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(exiger("agronome"))])
def deactivate_plant(plant_id: int, db: Session = Depends(get_db)):
    """Suppression logique : l'historique des diagnostics et irrigations reste cohérent."""
    plant = _get_or_404(db, plant_id)
    if plant.is_active:
        plant.is_active = False
        plant.params_version += 1
        _log(db, plant, "deactivate")
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{plant_id}/reactivate", response_model=PlantOut, dependencies=[Depends(exiger("agronome"))])
def reactivate_plant(plant_id: int, db: Session = Depends(get_db)):
    plant = _get_or_404(db, plant_id)
    if not plant.is_active:
        plant.is_active = True
        plant.params_version += 1
        _log(db, plant, "reactivate")
        db.commit()
    return plant


@router.get("/{plant_id}/historique", response_model=list[HistoryOut])
def plant_history(plant_id: int, db: Session = Depends(get_db)):
    _get_or_404(db, plant_id)
    q = select(PlantHistory).where(PlantHistory.plant_id == plant_id).order_by(PlantHistory.version)
    return db.scalars(q).all()


@router.post("/{plant_id}/varietes", response_model=PlantOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(exiger("agronome"))])
def add_variety(plant_id: int, payload: VarietyIn, db: Session = Depends(get_db)):
    plant = _get_or_404(db, plant_id)
    if any(v.nom == payload.nom for v in plant.varietes):
        raise HTTPException(409, "Cette variété existe déjà pour cette plante")
    plant.varietes.append(PlantVariety(nom=payload.nom))
    db.commit()
    return plant


@router.delete("/{plant_id}/varietes/{variete_id}", response_model=PlantOut, dependencies=[Depends(exiger("agronome"))])
def delete_variety(plant_id: int, variete_id: int, db: Session = Depends(get_db)):
    plant = _get_or_404(db, plant_id)
    variety = next((v for v in plant.varietes if v.id == variete_id), None)
    if not variety:
        raise HTTPException(404, "Variété introuvable")
    plant.varietes.remove(variety)
    db.commit()
    return plant
