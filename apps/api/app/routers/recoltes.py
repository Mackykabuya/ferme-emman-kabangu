"""Suivi des cultures : campagnes (du semis à la fin des récoltes), récoltes pesées, rendement (kg/ha) et eau utilisée par kg."""
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import exiger
from ..database import get_db
from ..models import Plant
from ..models_parcelles import Arrosage, Parcelle
from ..models_recoltes import Campagne, Recolte
from ..rapports import decalage

router = APIRouter(prefix="/recoltes", tags=["Récoltes et rendements"])
Qualite = Literal["A", "B", "C"]
LIM_ANNEES = 5


def _aujourdhui() -> date:
    from datetime import datetime as _d, timezone
    from ..engine import eau as moteur_eau
    return _d.now(timezone.utc).astimezone(moteur_eau.fuseau()).date()


def _borne(d: date) -> date:
    t = _aujourdhui()
    if not (t - timedelta(days=365 * LIM_ANNEES) <= d <= t + timedelta(days=365 * 2)):
        raise HTTPException(422, "Date invraisemblable (à plus de 5 ans dans le passé ou 2 ans dans le futur).")
    return d


class CampagneIn(BaseModel):
    parcelle_id: int
    plant_id: Optional[int] = None                       # par défaut : la plante actuelle de la parcelle
    semis_le: date
    recolte_prevue_le: Optional[date] = None
    note: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _ordre(self):
        if self.recolte_prevue_le and self.recolte_prevue_le < self.semis_le:
            raise ValueError("La récolte prévue ne peut pas précéder le semis")
        return self


class CampagneMaj(BaseModel):
    recolte_prevue_le: Optional[date] = None
    terminee_le: Optional[date] = None
    rouvrir: bool = False
    note: Optional[str] = Field(default=None, max_length=200)


class RecolteIn(BaseModel):
    campagne_id: int
    date: date
    quantite_kg: float = Field(gt=0, le=1_000_000)
    qualite: Qualite = "B"
    note: str = Field(default="", max_length=200)


def _eau_l(db: Session, c: Campagne) -> float:
    """Eau d'arrosage utilisée pendant la campagne (dates réelles ; l'horloge simulée est ramenée à la date du jour)."""
    fin = (c.terminee_le or _aujourdhui()) + timedelta(days=1)
    dec = decalage()
    q = select(func.coalesce(func.sum(Arrosage.litres), 0.0)).where(
        Arrosage.parcelle_id == c.parcelle_id, Arrosage.action == "ouvrir",
        Arrosage.at >= datetime.combine(c.semis_le, time.min) + dec, Arrosage.at < datetime.combine(fin, time.min) + dec)
    return float(db.scalar(q) or 0)


def _vue(db: Session, c: Campagne, noms: dict, plantes: dict) -> dict:
    rs = list(db.scalars(select(Recolte).where(Recolte.campagne_id == c.id)))
    kg = sum(r.quantite_kg for r in rs)
    surf = max((r.surface_m2 for r in rs), default=None) or (db.get(Parcelle, c.parcelle_id).surface_m2)
    eau = _eau_l(db, c)
    auj = _aujourdhui()
    jours = (c.recolte_prevue_le - auj).days if c.recolte_prevue_le and not c.terminee_le else None
    return {"id": c.id, "parcelle_id": c.parcelle_id, "parcelle": noms.get(c.parcelle_id, "?"), "plant_id": c.plant_id,
            "plante": plantes.get(c.plant_id, "?"), "semis_le": c.semis_le.isoformat(),
            "recolte_prevue_le": c.recolte_prevue_le.isoformat() if c.recolte_prevue_le else None,
            "terminee_le": c.terminee_le.isoformat() if c.terminee_le else None, "en_cours": c.terminee_le is None,
            "jours_avant_recolte": jours, "age_jours": ((c.terminee_le or auj) - c.semis_le).days, "note": c.note,
            "recoltes": len(rs), "total_kg": round(kg, 1), "surface_m2": surf,
            "rendement_kg_ha": round(kg / surf * 10000, 1) if kg and surf else None,
            "eau_l": round(eau), "eau_l_par_kg": round(eau / kg, 1) if kg and eau else None}


def _noms(db):
    return ({p.id: p.nom for p in db.scalars(select(Parcelle))}, {p.id: p.nom for p in db.scalars(select(Plant))})


@router.get("/campagnes")
def campagnes(parcelle_id: Optional[int] = None, en_cours: Optional[bool] = None, db: Session = Depends(get_db)):
    q = select(Campagne).order_by(Campagne.semis_le.desc(), Campagne.id.desc())
    if parcelle_id:
        q = q.where(Campagne.parcelle_id == parcelle_id)
    if en_cours is not None:
        q = q.where(Campagne.terminee_le.is_(None) if en_cours else Campagne.terminee_le.is_not(None))
    noms, plantes = _noms(db)
    return [_vue(db, c, noms, plantes) for c in db.scalars(q)]


@router.post("/campagnes", status_code=201, dependencies=[Depends(exiger("operateur"))])
def creer_campagne(req: CampagneIn, request: Request, db: Session = Depends(get_db)):
    p = db.get(Parcelle, req.parcelle_id)
    if not p:
        raise HTTPException(404, "Parcelle introuvable")
    plant = db.get(Plant, req.plant_id or p.plant_id)
    if not plant:
        raise HTTPException(404, "Plante introuvable")
    _borne(req.semis_le)
    if req.recolte_prevue_le:
        _borne(req.recolte_prevue_le)
    if db.scalar(select(Campagne.id).where(Campagne.parcelle_id == p.id, Campagne.terminee_le.is_(None))):
        raise HTTPException(409, "Cette parcelle a déjà une campagne en cours : terminez-la avant d'en ouvrir une autre.")
    c = Campagne(parcelle_id=p.id, plant_id=plant.id, semis_le=req.semis_le, recolte_prevue_le=req.recolte_prevue_le, note=req.note.strip())
    db.add(c)
    db.commit()
    request.state.journal_cible = f"{p.nom} · {plant.nom}"
    return _vue(db, c, *_noms(db))


@router.put("/campagnes/{cid}", dependencies=[Depends(exiger("operateur"))])
def modifier_campagne(cid: int, req: CampagneMaj, request: Request, db: Session = Depends(get_db)):
    c = db.get(Campagne, cid)
    if not c:
        raise HTTPException(404, "Campagne introuvable")
    ch = req.model_fields_set
    if "recolte_prevue_le" in ch:
        if req.recolte_prevue_le and req.recolte_prevue_le < c.semis_le:
            raise HTTPException(422, "La récolte prévue ne peut pas précéder le semis.")
        c.recolte_prevue_le = _borne(req.recolte_prevue_le) if req.recolte_prevue_le else None
    if req.note is not None:
        c.note = req.note.strip()
    if req.rouvrir:
        if db.scalar(select(Campagne.id).where(Campagne.parcelle_id == c.parcelle_id, Campagne.terminee_le.is_(None), Campagne.id != c.id)):
            raise HTTPException(409, "Une autre campagne est déjà en cours sur cette parcelle.")
        c.terminee_le = None
    elif req.terminee_le:
        if req.terminee_le < c.semis_le:
            raise HTTPException(422, "La fin ne peut pas précéder le semis.")
        c.terminee_le = _borne(req.terminee_le)
    db.commit()
    request.state.journal_cible = f"{db.get(Parcelle, c.parcelle_id).nom}"
    return _vue(db, c, *_noms(db))


@router.delete("/campagnes/{cid}", status_code=204, dependencies=[Depends(exiger("agronome"))])
def supprimer_campagne(cid: int, request: Request, db: Session = Depends(get_db)):
    c = db.get(Campagne, cid)
    if not c:
        raise HTTPException(404, "Campagne introuvable")
    request.state.journal_cible = db.get(Parcelle, c.parcelle_id).nom
    for r in db.scalars(select(Recolte).where(Recolte.campagne_id == cid)):
        db.delete(r)
    db.delete(c)
    db.commit()


def _vue_recolte(r: Recolte, noms: dict) -> dict:
    return {"id": r.id, "campagne_id": r.campagne_id, "parcelle_id": r.parcelle_id, "parcelle": noms.get(r.parcelle_id, "?"),
            "date": r.date.isoformat(), "quantite_kg": r.quantite_kg, "qualite": r.qualite, "note": r.note, "saisi_par": r.saisi_par}


@router.get("")
def lister(parcelle_id: Optional[int] = None, campagne_id: Optional[int] = None, jours: Optional[int] = Query(None, ge=1, le=3650),
           db: Session = Depends(get_db)):
    q = select(Recolte).order_by(Recolte.date.desc(), Recolte.id.desc())
    if parcelle_id:
        q = q.where(Recolte.parcelle_id == parcelle_id)
    if campagne_id:
        q = q.where(Recolte.campagne_id == campagne_id)
    if jours:
        q = q.where(Recolte.date >= _aujourdhui() - timedelta(days=jours))
    noms = _noms(db)[0]
    return [_vue_recolte(r, noms) for r in db.scalars(q.limit(500))]


@router.post("", status_code=201)
def enregistrer(req: RecolteIn, request: Request, db: Session = Depends(get_db), u=Depends(exiger("operateur"))):
    c = db.get(Campagne, req.campagne_id)
    if not c:
        raise HTTPException(404, "Campagne introuvable")
    if req.date < c.semis_le:
        raise HTTPException(422, "La récolte ne peut pas précéder le semis.")
    if req.date > _aujourdhui():
        raise HTTPException(422, "La date de récolte ne peut pas être dans le futur.")
    _borne(req.date)
    p = db.get(Parcelle, c.parcelle_id)
    r = Recolte(campagne_id=c.id, parcelle_id=c.parcelle_id, date=req.date, quantite_kg=round(req.quantite_kg, 2), qualite=req.qualite,
                surface_m2=p.surface_m2, note=req.note.strip(), saisi_par=u.identifiant)
    db.add(r)
    db.commit()
    request.state.journal_cible = p.nom
    request.state.journal_detail = f"{r.quantite_kg:g} kg · qualité {r.qualite}"
    return _vue_recolte(r, {p.id: p.nom})


@router.delete("/{rid}", status_code=204, dependencies=[Depends(exiger("agronome"))])
def supprimer(rid: int, request: Request, db: Session = Depends(get_db)):
    r = db.get(Recolte, rid)
    if not r:
        raise HTTPException(404, "Récolte introuvable")
    request.state.journal_cible = db.get(Parcelle, r.parcelle_id).nom
    db.delete(r)
    db.commit()


@router.get("/bilan")
def bilan(db: Session = Depends(get_db)):
    """Par plante : récolte totale, rendement moyen (kg/ha, toutes campagnes avec récolte) et eau utilisée par kg."""
    noms, plantes = _noms(db)
    par: dict[int, dict] = {}
    for c in db.scalars(select(Campagne)):
        v = _vue(db, c, noms, plantes)
        if not v["total_kg"]:
            continue
        b = par.setdefault(c.plant_id, {"plant_id": c.plant_id, "plante": v["plante"], "campagnes": 0, "kg": 0.0, "kg_ha_x_surf": 0.0, "surf": 0.0, "eau": 0.0})
        b["campagnes"] += 1
        b["kg"] += v["total_kg"]
        b["surf"] += v["surface_m2"] or 0
        b["eau"] += v["eau_l"]
    out = [{"plant_id": b["plant_id"], "plante": b["plante"], "campagnes": b["campagnes"], "total_kg": round(b["kg"], 1),
            "rendement_kg_ha": round(b["kg"] / b["surf"] * 10000, 1) if b["surf"] else None,
            "eau_l_par_kg": round(b["eau"] / b["kg"], 1) if b["kg"] and b["eau"] else None} for b in par.values()]
    return sorted(out, key=lambda x: -x["total_kg"])
