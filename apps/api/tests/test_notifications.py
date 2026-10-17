from datetime import timedelta

import pytest
from sqlalchemy import select

from app import notifications as nt
from app.auth import hacher
from app.models_auth import AlerteNotifiee, Utilisateur
from tests.test_plants import client  # noqa: F401


def alerte(code="capteur_bloque", pid=1, gravite="critique"):
    return {"code": code, "parcelle_id": pid, "parcelle": f"Parcelle {pid}", "gravite": gravite, "titre": "Capteur bloqué",
            "message": "Le capteur n'a pas bougé.", "conseil": "Vérifier le capteur."}


@pytest.fixture()
def cadre(client, monkeypatch):  # noqa: F811
    c, Session = client
    monkeypatch.setenv("SMTP_HOTE", "smtp.test")
    state = {"alertes": [alerte()], "envoyes": []}
    monkeypatch.setattr(nt, "toutes_les_alertes", lambda db: state["alertes"])
    with Session() as db:
        db.scalar(select(Utilisateur).where(Utilisateur.identifiant == "admin")).email = "admin@ferme.test"
        for ident, role, mail in (("agro", "agronome", "agro@ferme.test"), ("oper", "operateur", "oper@ferme.test"), ("lect", "lecteur", None)):
            db.add(Utilisateur(identifiant=ident, nom=ident, role=role, mdp_hash=hacher("motdepasse-test-1"), email=mail))
        db.commit()

    def envoyer(a, sujet, texte):
        state["envoyes"].append((a, sujet, texte))
        return True
    return Session, state, envoyer


def tour(Session, envoyer):
    with Session() as db:
        return nt.traiter(db, envoyer)


def test_destinataires_admin_et_agronome_seulement(cadre):
    Session, state, envoyer = cadre
    tour(Session, envoyer)
    assert sorted(a for a, *_ in state["envoyes"]) == ["admin@ferme.test", "agro@ferme.test"]
    sujet, texte = state["envoyes"][0][1:]
    assert "1 alerte" in sujet and "urgente" in sujet and "Parcelle 1" in texte and "Vérifier le capteur." in texte


def test_pas_de_repetition_puis_rappel_puis_nouvelle_alerte(cadre):
    Session, state, envoyer = cadre
    tour(Session, envoyer); n = len(state["envoyes"])
    tour(Session, envoyer)
    assert len(state["envoyes"]) == n                                   # déjà annoncée
    state["alertes"].append(alerte("pompe_trop_faible", 2, "attention"))
    tour(Session, envoyer)
    nouveaux = state["envoyes"][n:]
    assert len(nouveaux) == 2 and all("Parcelle 2" in t and "Parcelle 1" not in t for *_, t in nouveaux)   # seule la nouvelle est annoncée
    with Session() as db:                                               # vieillie de 13 h : rappel
        for x in db.scalars(select(AlerteNotifiee)):
            x.notifiee_le -= timedelta(hours=13)
        db.commit()
    n = len(state["envoyes"])
    tour(Session, envoyer)
    assert len(state["envoyes"]) == n + 2 and "Parcelle 1" in state["envoyes"][-1][2] and "Parcelle 2" in state["envoyes"][-1][2]


def test_alerte_resolue_puis_revenue_est_reannoncee(cadre):
    Session, state, envoyer = cadre
    tour(Session, envoyer)
    state["alertes"].clear(); tour(Session, envoyer)
    with Session() as db:
        assert db.scalars(select(AlerteNotifiee)).all() == []
    state["alertes"].append(alerte()); n = len(state["envoyes"])
    tour(Session, envoyer)
    assert len(state["envoyes"]) == n + 2


def test_info_ignoree_case_decochee_et_sans_smtp(cadre, monkeypatch):
    Session, state, envoyer = cadre
    state["alertes"][:] = [alerte(gravite="info")]
    assert tour(Session, envoyer)["envoyes"] == 0
    state["alertes"][:] = [alerte()]
    with Session() as db:
        db.scalar(select(Utilisateur).where(Utilisateur.identifiant == "agro")).notif_alertes = False
        db.commit()
    tour(Session, envoyer)
    assert [a for a, *_ in state["envoyes"]] == ["admin@ferme.test"]
    monkeypatch.delenv("SMTP_HOTE")
    state["alertes"].append(alerte("x", 9)); n = len(state["envoyes"])
    assert tour(Session, envoyer)["envoyes"] == 0 and len(state["envoyes"]) == n


def test_echec_d_envoi_reessaye_au_tour_suivant(cadre):
    Session, state, envoyer = cadre
    assert tour(Session, lambda *a: False)["envoyes"] == 0
    assert tour(Session, envoyer)["envoyes"] == 2


def test_api_case_notifications_et_courriel_de_test(client, monkeypatch):  # noqa: F811
    c, Session = client
    assert c.get("/auth/moi").json()["notif_alertes"] is True
    assert c.put("/auth/moi/notifications", json={"actif": False}).json()["notif_alertes"] is False
    assert c.post("/admin/test-courriel").status_code == 409                    # pas d'e-mail
    with Session() as db:
        db.scalar(select(Utilisateur).where(Utilisateur.identifiant == "admin")).email = "admin@ferme.test"
        db.commit()
    monkeypatch.delenv("SMTP_HOTE", raising=False)
    assert c.post("/admin/test-courriel").status_code == 409                    # SMTP absent
    monkeypatch.setenv("SMTP_HOTE", "smtp.test")
    vus = []
    monkeypatch.setattr("app.courriel.envoyer", lambda a, s, t: vus.append(a) or True)
    assert c.post("/admin/test-courriel").json() == {"envoye_a": "admin@ferme.test"} and vus == ["admin@ferme.test"]
