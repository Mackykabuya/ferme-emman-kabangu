from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..engine.diagnostic import diagnostiquer
from ..engine.irrigation import estimer_irrigation, fonction_prediction
from ..schemas_decision import DecisionRequest, DecisionResponse
from .diagnostic import mesures_sol, plante_active_ou_erreur, reponse_diagnostic
from .irrigation import reponse_irrigation

router = APIRouter(prefix="/decision", tags=["Décision complète (diagnostic puis arrosage)"])


@router.post("/parcelle", response_model=DecisionResponse)
def decision_parcelle(req: DecisionRequest, db: Session = Depends(get_db)):
    """Étape 1 : diagnostic du sol. Étape 2 : calcul de l'arrosage, corrigé selon le diagnostic."""
    plant = plante_active_ou_erreur(db, req.plant_id)
    diag = diagnostiquer(plant, mesures_sol(req), req.surface_parcelle_m2)
    irr = estimer_irrigation(plant, req.stade, req.temperature_air_c, req.humidite_air_pct, req.humidite_sol_pct,
                             req.type_sol, req.prevision_pluie_6h_mm, req.surface_parcelle_m2,
                             etat_sante=diag["etat_sante"], salinite_elevee=req.conductivite_ec_dsm > plant.ec_max_dsm,
                             predire_ratio=fonction_prediction())
    parties = [diag["message_simple"]]
    if diag["etat_sante"] != "Saine":
        parties.append(f"À faire en priorité : {diag['actions'][0]}")
    parties.append(irr.resume)
    if irr.vanne_ouverte:                      # ces précisions n'ont de sens que si on arrose
        parties += [irr.ajustement, irr.conseil_horaire]
    resume = " ".join(p for p in parties if p)
    return DecisionResponse(
        ordre=["1. Diagnostic du sol", "2. Calcul de l'arrosage (corrigé selon le diagnostic)"],
        etape_1_diagnostic=reponse_diagnostic(plant, diag),
        etape_2_irrigation=reponse_irrigation(plant, req.stade, irr),
        resume_agriculteur=resume)
