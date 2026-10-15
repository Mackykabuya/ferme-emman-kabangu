import pytest
from sqlalchemy import select

from app import ajouts
from app.models import Plant
from app.models_parcelles import Parcelle
from app.seed import seed_catalogue
from app.seed_parcelles import seed_parcelles
from tests.test_plants import client  # noqa: F401


@pytest.fixture()
def ferme(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DIAGNOSTIC_MODEL_PATH", "/inexistant")
    monkeypatch.setenv("IRRIGATION_MODEL_PATH", "/inexistant")
    c, Session = client
    with Session() as db:                                  # une base « d'avant » : catalogue + 10 parcelles, sans les ajouts
        seed_catalogue(db)
        seed_parcelles(db)
    return c, Session


def test_avocatier_et_palmier_ajoutes_sur_une_base_existante(ferme):
    c, Session = ferme
    with Session() as db:
        assert ajouts.appliquer(db) == ["Avocatier", "Palmier à huile", "Parcelle F1", "Parcelle F2"]
    liste = c.get("/parcelles").json()
    assert len(liste) == 12
    plantes = {p["nom"]: p["plante"] for p in liste}
    assert plantes["Parcelle F1"] == "Avocatier" and plantes["Parcelle F2"] == "Palmier à huile"
    noms = {p["nom"]: p for p in c.get("/plants").json()}
    assert {"Avocatier", "Palmier à huile"} <= set(noms)
    assert [v["nom"] for v in c.get(f"/plants/{noms["Avocatier"]["id"]}").json()["varietes"]] == ["Fuerte", "Hass", "Locale"]


def test_ajout_fait_une_seule_fois_meme_apres_suppression(ferme):
    c, Session = ferme
    with Session() as db:
        ajouts.appliquer(db)
        db.delete(db.scalar(select(Parcelle).where(Parcelle.nom == "Parcelle F1")))
        db.commit()
    with Session() as db:
        assert ajouts.appliquer(db) == []                  # le marqueur empêche de recréer la parcelle supprimée
        assert db.scalar(select(Parcelle.id).where(Parcelle.nom == "Parcelle F1")) is None
        assert len(db.scalars(select(Plant).where(Plant.nom.in_(["Avocatier", "Palmier à huile"]))).all()) == 2


def test_une_plante_deja_creee_par_l_utilisateur_est_respectee(ferme):
    c, Session = ferme
    with Session() as db:
        deja = Plant(nom="Avocatier", categorie="Fruits / Autres", kc_germination=0.5, kc_vegetative=0.5, kc_floraison=0.5,
                     kc_fructification=0.5, ph_min=6, ph_max=7, n_min=1, n_max=2, p_min=1, p_max=2, k_min=1, k_max=2,
                     ec_max_dsm=1, humidite_sol_min=50, humidite_sol_max=60, temp_opt_min=20, temp_opt_max=30,
                     tolerance_hydrique=3, densite_plants_ha=100, debit_plant_lph=10, source="user")
        db.add(deja)
        db.commit()
        assert ajouts.appliquer(db) == ["Palmier à huile", "Parcelle F1", "Parcelle F2"]
        assert db.scalar(select(Plant).where(Plant.nom == "Avocatier")).source == "user"     # non écrasée


def test_les_nouvelles_parcelles_ont_un_diagnostic_et_un_conseil_d_irrigation(ferme):
    c, Session = ferme
    with Session() as db:
        ajouts.appliquer(db)
    apercu = {p["nom"]: p for p in c.get("/parcelles/apercu?pluie=0").json()}
    assert len(apercu) == 12
    for nom in ("Parcelle F1", "Parcelle F2"):
        d = apercu[nom]["decision"]
        assert d["etape_1_diagnostic"]["etat_sante"] and "etape_2_irrigation" in d
    assert apercu["Parcelle F1"]["decision"]["etape_1_diagnostic"]["etat_sante"] == "Saine"
    assert apercu["Parcelle F2"]["decision"]["etape_1_diagnostic"]["etat_sante"] == "Saine"
