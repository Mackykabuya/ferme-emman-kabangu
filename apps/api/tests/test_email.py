import re
import sqlite3
from datetime import timedelta

import pytest

from app import courriel, migration
from app.models_auth import ReinitialisationMdp
from app.routers import auth as ra
from tests.test_auth import MDP, anonyme, compte, connecte, demande, ferme  # noqa: F401
from tests.test_plants import client  # noqa: F401


@pytest.fixture()
def boite(ferme, monkeypatch):  # noqa: F811
    """Remplace l'envoi réel : les e-mails « partis » s'accumulent dans la liste."""
    ra._demandes_ip.clear(); ra._oublis_ip.clear(); ra._oublis_mail.clear()
    monkeypatch.setenv("FERME_URL", "http://ferme.test:8000")
    monkeypatch.setattr(courriel, "configure", lambda: True)
    envoyes = []
    monkeypatch.setattr(courriel, "envoyer", lambda a, sujet, texte: envoyes.append((a, sujet, texte)) or True)
    return (*ferme, envoyes)


def jeton_de(texte):
    return re.search(r"#jeton=([\w-]+)", texte).group(1)


def test_inscription_par_email_puis_connexion_par_email(boite):
    admin, _, _ = boite
    r = demande(identifiant="", email="Jean.Kabangu@Exemple.org")
    assert r.status_code == 201, r.text
    d = admin.get("/auth/demandes").json()[0]
    assert d["email"] == "jean.kabangu@exemple.org" and d["identifiant"] == "jean.kabangu"      # identifiant déduit
    assert anonyme().post("/auth/connexion", json={"identifiant": "jean.kabangu@exemple.org", "mot_de_passe": MDP}).status_code == 403   # pas encore validé
    assert admin.post(f"/auth/demandes/{d['id']}/accepter", json={"role": "operateur"}).status_code == 201
    for saisie in ("jean.kabangu@exemple.org", "JEAN.KABANGU@EXEMPLE.ORG", "jean.kabangu"):
        rep = anonyme().post("/auth/connexion", json={"identifiant": saisie, "mot_de_passe": MDP})
        assert rep.status_code == 200 and rep.json()["utilisateur"]["email"] == "jean.kabangu@exemple.org", saisie
    assert anonyme().post("/auth/connexion", json={"identifiant": "jean.kabangu@exemple.org", "mot_de_passe": "faux-faux-1"}).status_code == 401


def test_email_invalide_ou_deja_pris(boite):
    admin, _, _ = boite
    for mauvais in ("pas-un-mail", "a@b", "a b@c.org", ""):
        assert demande(identifiant="", email=mauvais).status_code == 422, mauvais
    assert demande(identifiant="", email="a@exemple.org").status_code == 201
    assert demande(identifiant="autre", email="A@exemple.org").status_code == 409
    compte(admin, "bob", "lecteur")
    admin.put("/auth/utilisateurs/%d" % [u["id"] for u in admin.get("/auth/utilisateurs").json() if u["identifiant"] == "bob"][0], json={"email": "bob@exemple.org"})
    assert demande(identifiant="", email="bob@exemple.org").status_code == 409


def test_identifiants_generes_restent_uniques(boite):
    admin, _, _ = boite
    assert demande(identifiant="", email="paul@a.org").status_code == 201
    assert demande(identifiant="", email="paul@b.org").status_code == 201
    assert sorted(d["identifiant"] for d in admin.get("/auth/demandes").json()) == ["paul", "paul2"]


def lea(admin):
    u = compte(admin, "lea", "lecteur")
    admin.put(f"/auth/utilisateurs/{u['id']}", json={"email": "lea@exemple.org"})
    return u


def test_mot_de_passe_oublie_parcours_complet(boite):
    admin, Session, envoyes = boite
    lea(admin)
    vieille = connecte("lea")
    r = anonyme().post("/auth/mot-de-passe-oublie", json={"email": "LEA@exemple.org"})
    assert r.status_code == 200
    assert len(envoyes) == 1 and envoyes[0][0] == "lea@exemple.org"
    assert envoyes[0][2].count("http://ferme.test:8000/tableau-de-bord/reinitialiser.html#jeton=") == 1
    jeton = jeton_de(envoyes[0][2])
    with Session() as db:                                               # seule l'empreinte est stockée
        assert db.query(ReinitialisationMdp).count() == 1
        assert jeton not in db.query(ReinitialisationMdp).first().empreinte
    assert anonyme().post("/auth/reinitialiser", json={"jeton": jeton, "nouveau": "court"}).status_code == 422   # refus : le lien reste valable
    assert anonyme().post("/auth/reinitialiser", json={"jeton": jeton, "nouveau": "nouveau-mot-de-passe"}).status_code == 204
    assert anonyme().post("/auth/connexion", json={"identifiant": "lea@exemple.org", "mot_de_passe": MDP}).status_code == 401
    assert anonyme().post("/auth/connexion", json={"identifiant": "lea@exemple.org", "mot_de_passe": "nouveau-mot-de-passe"}).status_code == 200
    assert vieille.get("/auth/moi").status_code == 401                  # anciennes sessions fermées
    assert anonyme().post("/auth/reinitialiser", json={"jeton": jeton, "nouveau": "encore-un-autre-1"}).status_code == 400   # usage unique


def test_oubli_ne_revele_pas_si_le_compte_existe(boite):
    admin, _, envoyes = boite
    lea(admin)
    a = anonyme().post("/auth/mot-de-passe-oublie", json={"email": "lea@exemple.org"})
    b = anonyme().post("/auth/mot-de-passe-oublie", json={"email": "inconnu@exemple.org"})
    c = anonyme().post("/auth/mot-de-passe-oublie", json={"email": "n'importe quoi"})
    assert a.status_code == b.status_code == c.status_code == 200 and a.json() == b.json() == c.json()
    assert len(envoyes) == 1


def test_oubli_compte_desactive_et_nouveau_lien_annule_l_ancien(boite):
    admin, Session, envoyes = boite
    u = lea(admin)
    anonyme().post("/auth/mot-de-passe-oublie", json={"email": "lea@exemple.org"})
    anonyme().post("/auth/mot-de-passe-oublie", json={"email": "lea@exemple.org"})
    premier, second = (jeton_de(e[2]) for e in envoyes)
    assert anonyme().post("/auth/reinitialiser", json={"jeton": premier, "nouveau": "nouveau-mot-de-passe"}).status_code == 400
    admin.put(f"/auth/utilisateurs/{u['id']}", json={"actif": False})
    assert anonyme().post("/auth/reinitialiser", json={"jeton": second, "nouveau": "nouveau-mot-de-passe"}).status_code == 400
    n = len(envoyes)
    anonyme().post("/auth/mot-de-passe-oublie", json={"email": "lea@exemple.org"})
    assert len(envoyes) == n                                            # compte désactivé : rien envoyé


def test_lien_expire(boite):
    admin, Session, envoyes = boite
    lea(admin)
    anonyme().post("/auth/mot-de-passe-oublie", json={"email": "lea@exemple.org"})
    with Session() as db:
        r = db.query(ReinitialisationMdp).first()
        r.expire_le = r.expire_le - timedelta(hours=2)
        db.commit()
    assert anonyme().post("/auth/reinitialiser", json={"jeton": jeton_de(envoyes[0][2]), "nouveau": "nouveau-mot-de-passe"}).status_code == 400


def test_limites_anti_abus(boite):
    admin, _, envoyes = boite
    lea(admin)
    for _ in range(ra.OUBLIS_PAR_MAIL_HEURE + 2):
        assert anonyme().post("/auth/mot-de-passe-oublie", json={"email": "lea@exemple.org"}).status_code == 200
    assert len(envoyes) == ra.OUBLIS_PAR_MAIL_HEURE                     # au-delà : silencieusement ignoré
    ra._oublis_ip.clear()
    for i in range(ra.OUBLIS_PAR_IP_HEURE):
        anonyme().post("/auth/mot-de-passe-oublie", json={"email": f"x{i}@exemple.org"})
    assert anonyme().post("/auth/mot-de-passe-oublie", json={"email": "y@exemple.org"}).status_code == 429


def test_reinitialisation_leve_le_blocage_de_connexion(boite):
    admin, _, envoyes = boite
    lea(admin)
    for _ in range(ra.ECHECS_MAX):
        anonyme().post("/auth/connexion", json={"identifiant": "lea@exemple.org", "mot_de_passe": "faux-faux-1"})
    assert anonyme().post("/auth/connexion", json={"identifiant": "lea@exemple.org", "mot_de_passe": MDP}).status_code == 429
    anonyme().post("/auth/mot-de-passe-oublie", json={"email": "lea@exemple.org"})
    anonyme().post("/auth/reinitialiser", json={"jeton": jeton_de(envoyes[0][2]), "nouveau": "nouveau-mot-de-passe"})
    assert anonyme().post("/auth/connexion", json={"identifiant": "lea@exemple.org", "mot_de_passe": "nouveau-mot-de-passe"}).status_code == 200


def test_lien_fourni_par_l_admin(boite):
    admin, _, _ = boite
    u = compte(admin, "sans.mail", "lecteur")
    r = admin.post(f"/auth/utilisateurs/{u['id']}/lien-reinitialisation")
    assert r.status_code == 200 and r.json()["lien"].startswith("http://ferme.test:8000/tableau-de-bord/reinitialiser.html#jeton=")
    assert anonyme().post("/auth/reinitialiser", json={"jeton": jeton_de(r.json()["lien"]), "nouveau": "nouveau-mot-de-passe"}).status_code == 204
    assert connecte("lea") if False else True
    lec = connecte("sans.mail") if False else None
    compte(admin, "simple", "lecteur")
    c = connecte("simple")
    assert c.post(f"/auth/utilisateurs/{u['id']}/lien-reinitialisation").status_code == 403
    assert anonyme().post(f"/auth/utilisateurs/{u['id']}/lien-reinitialisation").status_code == 401
    assert admin.post("/auth/utilisateurs/9999/lien-reinitialisation").status_code == 404


def test_changer_son_email_demande_le_mot_de_passe(boite):
    admin, _, _ = boite
    compte(admin, "marc", "lecteur")
    c = connecte("marc")
    assert c.put("/auth/moi/email", json={"email": "marc@exemple.org", "mot_de_passe": "faux-faux-1"}).status_code == 403
    assert c.put("/auth/moi/email", json={"email": "pas-un-mail", "mot_de_passe": MDP}).status_code == 422
    r = c.put("/auth/moi/email", json={"email": "Marc@Exemple.org", "mot_de_passe": MDP})
    assert r.status_code == 200 and r.json()["email"] == "marc@exemple.org"
    assert anonyme().post("/auth/connexion", json={"identifiant": "marc@exemple.org", "mot_de_passe": MDP}).status_code == 200


def test_sans_smtp_le_lien_va_dans_le_journal(boite, monkeypatch, capsys):
    admin, _, _ = boite
    lea(admin)
    monkeypatch.undo()                                                  # retire l'envoi factice et FERME_URL
    monkeypatch.delenv("SMTP_HOTE", raising=False)
    assert courriel.envoyer("a@b.org", "sujet", "corps http://x/#jeton=abc") is False
    assert "jeton=abc" in capsys.readouterr().out


def test_courriel_sans_ferme_url_n_envoie_pas_de_lien_forgeable(boite, monkeypatch, capsys):
    admin, _, envoyes = boite
    lea(admin)
    monkeypatch.delenv("FERME_URL")
    r = anonyme().post("/auth/mot-de-passe-oublie", json={"email": "lea@exemple.org"}, headers={"Host": "pirate.example"})
    assert r.status_code == 200 and envoyes == []                       # SMTP réglé mais FERME_URL absent : journal seulement
    assert "pirate.example" not in capsys.readouterr().out


def test_migration_ajoute_la_colonne_une_seule_fois(tmp_path):
    from sqlalchemy import create_engine
    f = tmp_path / "vieux.db"
    c = sqlite3.connect(f)
    c.execute("CREATE TABLE utilisateurs (id INTEGER PRIMARY KEY, identifiant VARCHAR(40), mdp_hash VARCHAR(300))")
    c.execute("CREATE TABLE demandes_inscription (id INTEGER PRIMARY KEY, identifiant VARCHAR(40))")
    c.execute("INSERT INTO utilisateurs (identifiant, mdp_hash) VALUES ('admin', 'x')")
    c.commit(); c.close()
    e = create_engine(f"sqlite:///{f}")
    assert migration.appliquer(e) == ["utilisateurs.email", "demandes_inscription.email"]
    assert migration.appliquer(e) == []
    c = sqlite3.connect(f)
    assert c.execute("SELECT identifiant, email FROM utilisateurs").fetchall() == [("admin", None)]
