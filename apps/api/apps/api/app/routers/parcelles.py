import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..engine.anomalies import FENETRE_BLOQUE, capteur_suspect
from ..models import Plant
from ..auth import a_le_role, exiger
from ..models_parcelles import Arrosage, Mesure, Parcelle, maintenant
from ..schemas_decision import DecisionRequest
from ..schemas_irrigation import Stade
from .decision import decision_parcelle
from .meteo import METEO

router = APIRouter(prefix="/parcelles", tags=["Parcelles et vannes"])
DUREE_MAX_MIN = 120      # une vanne ne reste jamais ouverte plus de 2 h sans nouvelle commande
Sol = Literal["Sableux", "Limoneux", "Argileux"]


class ParcelleIn(BaseModel):
    nom: str = Field(min_length=2, max_length=60)
    surface_m2: float = Field(gt=0, le=200000)
    type_sol: Sol = "Limoneux"
    plant_id: int
    stade: Stade = "Croissance végétative"
    mode: Literal["auto", "manuel"] = "auto"


class ParcelleMaj(BaseModel):
    nom: Optional[str] = Field(default=None, min_length=2, max_length=60)
    surface_m2: Optional[float] = Field(default=None, gt=0, le=200000)
    type_sol: Optional[Sol] = None
    plant_id: Optional[int] = None
    stade: Optional[Stade] = None
    mode: Optional[Literal["auto", "manuel"]] = None
    mesures: Optional[dict[str, float]] = None
    horodatage: Optional[datetime] = None       # heure de la mesure (le simulateur envoie son horloge simulée)


class VanneCmd(BaseModel):
    action: Literal["ouvrir", "fermer"]
    duree_min: int = Field(default=30, ge=1, le=DUREE_MAX_MIN)


def _air(t: Optional[float] = Query(None, ge=-5, le=55), h: Optional[float] = Query(None, ge=0, le=100),
         pluie: Optional[float] = Query(None, ge=0, le=300)):
    """Météo de la requête ; à défaut, la météo du moment (PUT /meteo)."""
    return {"temperature_air_c": METEO["temperature_air_c"] if t is None else t,
            "humidite_air_pct": METEO["humidite_air_pct"] if h is None else h,
            "prevision_pluie_6h_mm": METEO["prevision_pluie_6h_mm"] if pluie is None else pluie}


def _get(db: Session, pid: int) -> Parcelle:
    p = db.get(Parcelle, pid)
    if not p:
        raise HTTPException(404, "Parcelle introuvable")
    return p


def _plante(db: Session, plant_id: int) -> Plant:
    plant = db.get(Plant, plant_id)
    if not plant or not plant.is_active:
        raise HTTPException(404, "Plante introuvable ou désactivée")
    return plant


def vue(p: Parcelle, plante: str) -> dict:
    return {"id": p.id, "nom": p.nom, "surface_m2": p.surface_m2, "type_sol": p.type_sol, "plant_id": p.plant_id,
            "plante": plante, "stade": p.stade, "mode": p.mode, "mesures": p.mesures,
            "vanne_ouverte": p.vanne_ouverte, "vanne_fin": p.vanne_fin.isoformat() if p.vanne_ouverte else None}


def _decision(db: Session, p: Parcelle, air: dict):
    return decision_parcelle(DecisionRequest(plant_id=p.plant_id, stade=p.stade, type_sol=p.type_sol,
                                             surface_parcelle_m2=p.surface_m2, **p.mesures, **air), db)


def _ouvrir(db: Session, p: Parcelle, minutes: int, source: str):
    plant = db.get(Plant, p.plant_id)
    litres = minutes / 60 * plant.debit_plant_lph * p.surface_m2 * plant.densite_plants_ha / 10000
    p.vanne_fin = maintenant() + timedelta(minutes=minutes)
    db.add(Arrosage(parcelle_id=p.id, action="ouvrir", minutes=minutes, litres=round(litres, 1), source=source))


@router.get("")
def liste(db: Session = Depends(get_db)):
    return [vue(p, db.get(Plant, p.plant_id).nom) for p in db.scalars(select(Parcelle).order_by(Parcelle.nom))]


@router.get("/apercu")
def apercu(air: dict = Depends(_air), db: Session = Depends(get_db)):
    """Toutes les parcelles avec, pour chacune, le diagnostic du sol puis la décision d'arrosage."""
    sortie = []
    for p in db.scalars(select(Parcelle).order_by(Parcelle.nom)):
        try:
            d = _decision(db, p, air)
        except HTTPException:
            d = None
        sortie.append({**vue(p, db.get(Plant, p.plant_id).nom), "decision": d})
    return sortie


DEBIT_POMPE_LH = float(os.getenv("DEBIT_POMPE_LH", 120000))   # capacité de la pompe en litres/heure, à régler


def _plages() -> list[tuple[float, float]]:
    """Heures où l'arrosage automatique est autorisé (PLAGES_ARROSAGE="5-9,17-20")."""
    return [tuple(map(float, x.split("-"))) for x in os.getenv("PLAGES_ARROSAGE", "5-9,17-20").split(",")]


def texte_plages() -> str:
    return ", ".join(f"{a:g} h-{b:g} h" for a, b in _plages())


def heure_locale() -> float:
    try:
        fuseau = ZoneInfo(os.getenv("FERME_FUSEAU", "Africa/Kinshasa"))
    except Exception:
        fuseau = timezone(timedelta(hours=1))
    n = datetime.now(fuseau)
    return n.hour + n.minute / 60


def dans_plage(heure: float) -> bool:
    return any(a <= heure < b for a, b in _plages())


def _debit(db: Session, p: Parcelle) -> float:
    plant = db.get(Plant, p.plant_id)
    return plant.debit_plant_lph * p.surface_m2 * plant.densite_plants_ha / 10000


def historique_mesures(db: Session, pid: int, n: int = 12) -> list[dict]:
    """Les n dernières mesures d'une parcelle, de la plus ancienne à la plus récente (pour la détection d'anomalies)."""
    lignes = list(db.scalars(select(Mesure).where(Mesure.parcelle_id == pid).order_by(Mesure.id.desc()).limit(n)))[::-1]
    return [{"at": m.at, "mesures": m.mesures, "vanne_ouverte": m.vanne_ouverte} for m in lignes]


def passe_auto(db: Session, air: dict, debit_pompe: float, heure: float | None = None) -> dict:
    """Ouvre les vannes des parcelles « auto » qui ont soif, les plus urgentes d'abord, sans dépasser la capacité
    de la pompe (les autres attendent la passe suivante) et seulement pendant les plages d'arrosage,
    sauf si le sol est vraiment trop sec."""
    heure = heure_locale() if heure is None else heure
    parcelles = list(db.scalars(select(Parcelle)))
    utilise = sum(_debit(db, p) for p in parcelles if p.vanne_ouverte)
    candidats, hors, suspects = [], [], []
    for p in parcelles:
        if p.mode != "auto" or p.vanne_ouverte:
            continue
        if capteur_suspect(historique_mesures(db, p.id, FENETRE_BLOQUE)):      # on n'arrose pas sur la foi d'un capteur douteux
            suspects.append(p.nom)
            continue
        try:
            irr = _decision(db, p, air).etape_2_irrigation
        except HTTPException:
            continue
        if irr.vanne_ouverte:
            plant = db.get(Plant, p.plant_id)
            urgence = (p.mesures["humidite_sol_pct"] - plant.humidite_sol_min) / (plant.humidite_sol_max - plant.humidite_sol_min)
            critique = p.mesures["humidite_sol_pct"] < plant.humidite_sol_min - 10      # sol vraiment trop sec
            if not (dans_plage(heure) or critique):
                hors.append(p.nom)
                continue
            candidats.append((urgence, p, irr))
    ouvertes, attente = [], []
    for _, p, irr in sorted(candidats, key=lambda c: c[0]):
        d = _debit(db, p)
        if utilise == 0 or utilise + d <= debit_pompe:
            _ouvrir(db, p, min(DUREE_MAX_MIN, max(1, irr.duree_min)), "auto")
            utilise += d
            ouvertes.append(p.nom)
        else:
            attente.append(p.nom)
    db.commit()
    return {"vannes_ouvertes": ouvertes, "en_attente_de_pompe": attente, "hors_plage_horaire": hors, "capteur_douteux": suspects,
            "plages": texte_plages(), "debit_utilise_lh": round(utilise)}


@router.post("/appliquer-auto", dependencies=[Depends(exiger("operateur"))])
def appliquer_auto(air: dict = Depends(_air), debit_pompe: float = Query(DEBIT_POMPE_LH, gt=0),
                   heure: Optional[float] = Query(None, ge=0, lt=24, description="heure locale ; par défaut l'heure réelle"),
                   db: Session = Depends(get_db)):
    return passe_auto(db, air, debit_pompe, heure)


def planifier():
    """Une passe automatique avec la météo du moment (appelée périodiquement par main.py)."""
    from ..simulation import actif
    if actif():          # la simulation pilote elle-même les passes automatiques (avec son heure simulée)
        return None
    with SessionLocal() as db:
        return passe_auto(db, dict(METEO), DEBIT_POMPE_LH)


@router.post("", status_code=201, dependencies=[Depends(exiger("agronome"))])
def creer(req: ParcelleIn, db: Session = Depends(get_db)):
    from ..seed_parcelles import mesures_defaut
    plant = _plante(db, req.plant_id)
    if db.scalar(select(Parcelle.id).where(Parcelle.nom == req.nom)):
        raise HTTPException(409, f"Une parcelle nommée « {req.nom} » existe déjà")
    p = Parcelle(**req.model_dump(), mesures=mesures_defaut(plant))
    db.add(p)
    db.commit()
    return vue(p, plant.nom)


@router.get("/{pid}")
def detail(pid: int, db: Session = Depends(get_db)):
    p = _get(db, pid)
    return vue(p, db.get(Plant, p.plant_id).nom)


@router.put("/{pid}")
def modifier(pid: int, req: ParcelleMaj, db: Session = Depends(get_db), u=Depends(exiger("operateur"))):
    p = _get(db, pid)
    ch = req.model_dump(exclude_unset=True)
    if set(ch) & {"nom", "surface_m2", "type_sol", "plant_id", "stade"} and not a_le_role(u, "agronome"):
        raise HTTPException(403, "Droits insuffisants : changer la culture, le sol, le stade ou la surface demande le rôle "
                                 "« agronome » (un opérateur peut changer le mode et envoyer des mesures).")
    if "plant_id" in ch:
        _plante(db, ch["plant_id"])
    if "nom" in ch and db.scalar(select(Parcelle.id).where(Parcelle.nom == ch["nom"], Parcelle.id != pid)):
        raise HTTPException(409, "Ce nom est déjà utilisé")
    quand = ch.pop("horodatage", None)
    if "mesures" in ch:
        ch["mesures"] = {**p.mesures, **ch["mesures"]}
        if quand and quand.tzinfo:
            quand = quand.astimezone(timezone.utc).replace(tzinfo=None)
        db.add(Mesure(parcelle_id=pid, at=quand or maintenant(), mesures=ch["mesures"], vanne_ouverte=p.vanne_ouverte))
    for k, v in ch.items():
        setattr(p, k, v)
    db.commit()
    return vue(p, db.get(Plant, p.plant_id).nom)


@router.delete("/{pid}", status_code=204, dependencies=[Depends(exiger("agronome"))])
def supprimer(pid: int, db: Session = Depends(get_db)):
    p = _get(db, pid)
    for a in [*db.scalars(select(Arrosage).where(Arrosage.parcelle_id == pid)),
              *db.scalars(select(Mesure).where(Mesure.parcelle_id == pid))]:
        db.delete(a)
    db.delete(p)
    db.commit()


@router.post("/{pid}/vanne", dependencies=[Depends(exiger("operateur"))])
def vanne(pid: int, cmd: VanneCmd, db: Session = Depends(get_db)):
    p = _get(db, pid)
    if cmd.action == "ouvrir":
        _ouvrir(db, p, cmd.duree_min, "manuel")
    elif p.vanne_ouverte:
        p.vanne_fin = maintenant()
        db.add(Arrosage(parcelle_id=pid, action="fermer", minutes=0, litres=0, source="manuel"))
    db.commit()
    return vue(p, db.get(Plant, p.plant_id).nom)


@router.get("/{pid}/historique")
def historique(pid: int, db: Session = Depends(get_db)):
    _get(db, pid)
    q = select(Arrosage).where(Arrosage.parcelle_id == pid).order_by(Arrosage.id.desc()).limit(20)
    return [{"action": a.action, "minutes": a.minutes, "litres": a.litres, "source": a.source,
             "date": a.at.isoformat()} for a in db.scalars(q)]


@router.get("/{pid}/mesures")
def mesures(pid: int, limit: int = Query(240, ge=2, le=2000), db: Session = Depends(get_db)):
    """Les `limit` dernières mesures de la parcelle, dans l'ordre chronologique (pour les graphiques)."""
    _get(db, pid)
    q = select(Mesure).where(Mesure.parcelle_id == pid).order_by(Mesure.at.desc(), Mesure.id.desc()).limit(limit)
    return [{"date": m.at.isoformat(), "vanne_ouverte": m.vanne_ouverte, **m.mesures} for m in reversed(list(db.scalars(q)))]
