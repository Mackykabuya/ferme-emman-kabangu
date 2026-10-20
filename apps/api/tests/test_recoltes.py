from datetime import date, timedelta

from sqlalchemy import select

from app.models_parcelles import Arrosage, Parcelle, maintenant
from app.routers.recoltes import _aujourdhui
from tests.test_auth import MDP, anonyme, compte, connecte, ferme  # noqa: F401
from tests.test_plants import client  # noqa: F401


def jour(n=0):
    return (_aujourdhui() + timedelta(days=n)).isoformat()


def une_parcelle(admin):
    return admin.get("/parcelles").json()[0]


def ouvrir(admin, pid=None, **kw):
    pid = pid or une_parcelle(admin)["id"]
    corps = {"parcelle_id": pid, "semis_le": jour(-60), "recolte_prevue_le": jour(10), **kw}
    r = admin.post("/recoltes/campagnes", json=corps)
    assert r.status_code == 201, r.text
    return r.json()


def test_campagne_calendrier_et_une_seule_en_cours(ferme):
    admin, _ = ferme
    c = ouvrir(admin)
    assert c["en_cours"] and c["jours_avant_recolte"] == 10 and c["age_jours"] == 60 and c["plante"]
    assert admin.post("/recoltes/campagnes", json={"parcelle_id": c["parcelle_id"], "semis_le": jour(-1)}).status_code == 409
    r = admin.put(f"/recoltes/campagnes/{c['id']}", json={"recolte_prevue_le": jour(-3)})
    assert r.json()["jours_avant_recolte"] == -3                                    # en retard : négatif
    assert admin.post("/recoltes/campagnes", json={"parcelle_id": 9999, "semis_le": jour()}).status_code == 404
    assert admin.post("/recoltes/campagnes", json={"parcelle_id": c["parcelle_id"], "semis_le": "2010-01-01"}).status_code in (409, 422)


def test_dates_incoherentes_refusees(ferme):
    admin, _ = ferme
    pid = une_parcelle(admin)["id"]
    assert admin.post("/recoltes/campagnes", json={"parcelle_id": pid, "semis_le": jour(-5), "recolte_prevue_le": jour(-9)}).status_code == 422
    assert admin.post("/recoltes/campagnes", json={"parcelle_id": pid, "semis_le": "2010-01-01"}).status_code == 422


def test_recolte_rendement_et_eau(ferme):
    admin, Session = ferme
    c = ouvrir(admin)
    pid = c["parcelle_id"]
    with Session() as db:
        surface = db.get(Parcelle, pid).surface_m2
        db.add(Arrosage(parcelle_id=pid, action="ouvrir", minutes=30, litres=500.0, source="manuel", at=maintenant()))
        db.commit()
    assert admin.post("/recoltes", json={"campagne_id": c["id"], "date": jour(-1), "quantite_kg": 120.5, "qualite": "A"}).status_code == 201
    assert admin.post("/recoltes", json={"campagne_id": c["id"], "date": jour(), "quantite_kg": 79.5}).status_code == 201
    v = admin.get("/recoltes/campagnes").json()[0]
    assert v["total_kg"] == 200.0 and v["recoltes"] == 2
    assert v["rendement_kg_ha"] == round(200 / surface * 10000, 1)
    assert v["eau_l"] == 500 and v["eau_l_par_kg"] == 2.5
    b = admin.get("/recoltes/bilan").json()
    assert len(b) == 1 and b[0]["total_kg"] == 200.0 and b[0]["campagnes"] == 1
    assert len(admin.get("/recoltes", params={"campagne_id": c["id"]}).json()) == 2


def test_recolte_validations(ferme):
    admin, _ = ferme
    c = ouvrir(admin)
    base = {"campagne_id": c["id"], "date": jour(-1), "quantite_kg": 10}
    assert admin.post("/recoltes", json={**base, "quantite_kg": 0}).status_code == 422
    assert admin.post("/recoltes", json={**base, "quantite_kg": -5}).status_code == 422
    assert admin.post("/recoltes", json={**base, "qualite": "Z"}).status_code == 422
    assert admin.post("/recoltes", json={**base, "date": jour(3)}).status_code == 422          # dans le futur
    assert admin.post("/recoltes", json={**base, "date": jour(-90)}).status_code == 422        # avant le semis
    assert admin.post("/recoltes", json={**base, "campagne_id": 999}).status_code == 404


def test_terminer_rouvrir_et_supprimer(ferme):
    admin, _ = ferme
    c = ouvrir(admin)
    r = admin.put(f"/recoltes/campagnes/{c['id']}", json={"terminee_le": jour()})
    assert r.json()["en_cours"] is False and r.json()["jours_avant_recolte"] is None
    assert admin.put(f"/recoltes/campagnes/{c['id']}", json={"terminee_le": jour(-90)}).status_code == 422
    n = ouvrir(admin, semis_le=jour(-1), recolte_prevue_le=None)                  # une nouvelle campagne est alors possible
    assert admin.put(f"/recoltes/campagnes/{c['id']}", json={"rouvrir": True}).status_code == 409
    rec = admin.post("/recoltes", json={"campagne_id": n["id"], "date": jour(), "quantite_kg": 5}).json()
    assert admin.delete(f"/recoltes/{rec['id']}").status_code == 204
    assert admin.delete(f"/recoltes/{rec['id']}").status_code == 404
    assert admin.delete(f"/recoltes/campagnes/{n['id']}").status_code == 204
    assert len(admin.get("/recoltes/campagnes").json()) == 1


def test_roles(ferme):
    admin, _ = ferme
    compte(admin, "lect", "lecteur"); compte(admin, "oper", "operateur"); compte(admin, "agro", "agronome")
    c = ouvrir(admin)
    lect, oper, agro = connecte("lect"), connecte("oper"), connecte("agro")
    assert lect.get("/recoltes/campagnes").status_code == 200 and lect.get("/recoltes/bilan").status_code == 200
    corps = {"campagne_id": c["id"], "date": jour(), "quantite_kg": 4}
    assert lect.post("/recoltes", json=corps).status_code == 403
    assert lect.post("/recoltes/campagnes", json={"parcelle_id": c["parcelle_id"], "semis_le": jour()}).status_code == 403
    r = oper.post("/recoltes", json=corps)
    assert r.status_code == 201 and r.json()["saisi_par"] == "oper"
    assert oper.delete(f"/recoltes/{r.json()['id']}").status_code == 403                  # supprimer : agronome et plus
    assert agro.delete(f"/recoltes/{r.json()['id']}").status_code == 204
    assert anonyme().get("/recoltes/campagnes").status_code == 401


def test_suppression_de_parcelle_nettoie_les_campagnes(ferme):
    admin, Session = ferme
    c = ouvrir(admin)
    admin.post("/recoltes", json={"campagne_id": c["id"], "date": jour(), "quantite_kg": 5})
    assert admin.delete(f"/parcelles/{c['parcelle_id']}").status_code == 204
    assert admin.get("/recoltes/campagnes").json() == [] and admin.get("/recoltes").json() == []


def test_journal_note_les_recoltes(ferme):
    admin, _ = ferme
    c = ouvrir(admin)
    admin.post("/recoltes", json={"campagne_id": c["id"], "date": jour(), "quantite_kg": 7.5, "qualite": "A"})
    actions = admin.get("/admin/journal").json()["actions"]
    assert any(a["action"] == "Récolte enregistrée" and "7.5 kg" in a["detail"] for a in actions)
    assert any(a["action"] == "Campagne ouverte" for a in actions)
