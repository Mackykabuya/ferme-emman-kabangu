from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth
from app.main import app
from app.models_auth import SessionAuth, Utilisateur
from app.routers import auth as routeur_auth
from app.seed import seed_catalogue
from app.seed_parcelles import seed_parcelles
from tests.test_plants import NOUVELLE, client  # noqa: F401

MDP = "un-bon-mot-de-passe"


@pytest.fixture()
def ferme(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DIAGNOSTIC_MODEL_PATH", "/inexistant")
    monkeypatch.setenv("IRRIGATION_MODEL_PATH", "/inexistant")
    routeur_auth._echecs.clear()
    admin, Session = client
    with Session() as db:
        seed_catalogue(db)
        seed_parcelles(db)
    return admin, Session


def anonyme():
    return TestClient(app)


def compte(admin, identifiant, role):
    r = admin.post("/auth/utilisateurs", json={"identifiant": identifiant, "nom": identifiant.title(), "role": role, "mot_de_passe": MDP})
    assert r.status_code == 201, r.text
    return r.json()


def connecte(identifiant):
    c = anonyme()
    r = c.post("/auth/connexion", json={"identifiant": identifiant, "mot_de_passe": MDP})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['jeton']}"
    return c


def test_tout_est_protege_sauf_la_connexion(ferme):
    c = anonyme()
    for chemin in ("/parcelles", "/plants", "/alertes", "/eau", "/meteo", "/simulation", "/parcelles/apercu", "/auth/moi"):
        assert c.get(chemin).status_code == 401, chemin
    assert c.post("/parcelles/1/vanne", json={"action": "fermer"}).status_code == 401
    assert c.get("/tableau-de-bord/login.html").status_code in (200, 404)      # les pages sont publiques (aucune donnée dedans)
    assert c.post("/auth/connexion", json={"identifiant": "x", "mot_de_passe": "y"}).status_code == 401
    assert c.get("/parcelles", headers={"Authorization": "Bearer n-importe-quoi"}).status_code == 401


def test_connexion_message_identique_et_jeton_non_stocke_en_clair(ferme):
    admin, Session = ferme
    c = anonyme()
    inconnu = c.post("/auth/connexion", json={"identifiant": "personne", "mot_de_passe": "xxxxxxxx"})
    faux = c.post("/auth/connexion", json={"identifiant": "admin", "mot_de_passe": "mauvais-mdp"})
    assert inconnu.status_code == faux.status_code == 401 and inconnu.json() == faux.json()     # n'indique pas si le compte existe
    ok = c.post("/auth/connexion", json={"identifiant": "ADMIN", "mot_de_passe": "motdepasse-test"})      # identifiant insensible à la casse
    assert ok.status_code == 200 and ok.json()["utilisateur"]["role"] == "admin"
    jeton = ok.json()["jeton"]
    with Session() as db:
        assert jeton not in {s.empreinte for s in db.scalars(select(SessionAuth))}
        assert all(u.mdp_hash.startswith("scrypt$") and "motdepasse-test" not in u.mdp_hash for u in db.scalars(select(Utilisateur)))
    assert c.get("/auth/moi", headers={"Authorization": f"Bearer {jeton}"}).json()["identifiant"] == "admin"


def test_blocage_apres_cinq_echecs(ferme):
    c = anonyme()
    for _ in range(5):
        assert c.post("/auth/connexion", json={"identifiant": "admin", "mot_de_passe": "faux-faux"}).status_code == 401
    r = c.post("/auth/connexion", json={"identifiant": "admin", "mot_de_passe": "motdepasse-test"})
    assert r.status_code == 429 and "Patientez" in r.json()["detail"]


def test_lecteur_voit_tout_ne_modifie_rien(ferme):
    admin, _ = ferme
    compte(admin, "lea", "lecteur")
    c = connecte("lea")
    for chemin in ("/parcelles", "/parcelles/apercu", "/plants", "/alertes", "/eau", "/simulation"):
        assert c.get(chemin).status_code == 200, chemin
    assert c.post("/decision/parcelle", json={}).status_code == 422             # calcul autorisé (échoue seulement sur le contenu)
    r = c.post("/parcelles/1/vanne", json={"action": "ouvrir", "duree_min": 30})
    assert r.status_code == 403 and "opérateur" in r.json()["detail"] and "lecteur" in r.json()["detail"]
    assert c.post("/plants", json=NOUVELLE).status_code == 403
    assert c.put("/meteo", json={"temperature_air_c": 30, "humidite_air_pct": 50, "prevision_pluie_6h_mm": 0}).status_code == 403
    assert c.post("/simulation/pause").status_code == 403
    assert c.get("/auth/utilisateurs").status_code == 403


def test_operateur_pilote_les_vannes_pas_la_ferme(ferme):
    admin, _ = ferme
    compte(admin, "omar", "operateur")
    c = connecte("omar")
    assert c.post("/parcelles/1/vanne", json={"action": "ouvrir", "duree_min": 30}).status_code == 200
    assert c.put("/parcelles/1", json={"mode": "manuel"}).status_code == 200
    assert c.put("/parcelles/1", json={"mesures": {"humidite_sol_pct": 40}}).status_code == 200      # un capteur peut envoyer des mesures
    assert c.put("/meteo", json={"temperature_air_c": 30, "humidite_air_pct": 50, "prevision_pluie_6h_mm": 0}).status_code == 200
    for corps in ({"plant_id": 2}, {"surface_m2": 100}, {"nom": "Autre"}, {"stade": "Floraison"}, {"type_sol": "Sableux"}):
        r = c.put("/parcelles/1", json=corps)
        assert r.status_code == 403 and "agronome" in r.json()["detail"], corps
    assert c.post("/parcelles", json={"nom": "Parcelle Z", "surface_m2": 100, "plant_id": 2}).status_code == 403
    assert c.delete("/parcelles/1").status_code == 403
    assert c.post("/plants", json=NOUVELLE).status_code == 403


def test_agronome_gere_catalogue_et_parcelles_pas_les_comptes(ferme):
    admin, _ = ferme
    compte(admin, "agathe", "agronome")
    c = connecte("agathe")
    assert c.post("/plants", json=NOUVELLE).status_code == 201
    r = c.post("/parcelles", json={"nom": "Parcelle Z", "surface_m2": 100, "plant_id": 2})
    assert r.status_code == 201
    assert c.put(f"/parcelles/{r.json()['id']}", json={"surface_m2": 150}).status_code == 200
    assert c.delete(f"/parcelles/{r.json()['id']}").status_code == 204
    assert c.get("/auth/utilisateurs").status_code == 403
    assert c.post("/auth/utilisateurs", json={"identifiant": "pirate", "nom": "Pirate", "role": "admin", "mot_de_passe": MDP}).status_code == 403


def test_gestion_des_comptes_par_ladmin(ferme):
    admin, _ = ferme
    u = compte(admin, "paul", "lecteur")
    assert admin.post("/auth/utilisateurs", json={"identifiant": "paul", "nom": "Paul 2", "role": "lecteur", "mot_de_passe": MDP}).status_code == 409
    assert admin.post("/auth/utilisateurs", json={"identifiant": "court", "nom": "Court", "role": "lecteur", "mot_de_passe": "123"}).status_code == 422
    assert admin.post("/auth/utilisateurs", json={"identifiant": "Mauvais Id!", "nom": "Mauvais", "role": "lecteur", "mot_de_passe": MDP}).status_code == 422
    c = connecte("paul")
    assert c.post("/parcelles/1/vanne", json={"action": "ouvrir", "duree_min": 10}).status_code == 403
    admin.put(f"/auth/utilisateurs/{u['id']}", json={"role": "operateur"})          # le nouveau rôle s'applique tout de suite
    assert c.post("/parcelles/1/vanne", json={"action": "ouvrir", "duree_min": 10}).status_code == 200
    admin.put(f"/auth/utilisateurs/{u['id']}", json={"actif": False})               # désactivé : jeton immédiatement inutilisable
    assert c.get("/parcelles").status_code == 401
    assert anonyme().post("/auth/connexion", json={"identifiant": "paul", "mot_de_passe": MDP}).status_code == 401
    admin.put(f"/auth/utilisateurs/{u['id']}", json={"actif": True, "mot_de_passe": "nouveau-mdp-123"})
    assert anonyme().post("/auth/connexion", json={"identifiant": "paul", "mot_de_passe": "nouveau-mdp-123"}).status_code == 200


def test_on_ne_peut_pas_perdre_le_dernier_admin(ferme):
    admin, _ = ferme
    moi = admin.get("/auth/moi").json()
    assert admin.put(f"/auth/utilisateurs/{moi['id']}", json={"role": "lecteur"}).status_code == 409
    assert admin.put(f"/auth/utilisateurs/{moi['id']}", json={"actif": False}).status_code == 409
    autre = compte(admin, "second", "admin")
    assert admin.put(f"/auth/utilisateurs/{autre['id']}", json={"role": "lecteur"}).status_code == 200      # un autre admin existe
    assert admin.put(f"/auth/utilisateurs/{moi['id']}", json={"actif": False}).status_code == 409           # mais pas soi-même


def test_deconnexion_expiration_et_changement_de_mot_de_passe(ferme):
    admin, Session = ferme
    compte(admin, "sam", "lecteur")
    c1, c2 = connecte("sam"), connecte("sam")
    assert c1.post("/auth/deconnexion").status_code == 204
    assert c1.get("/parcelles").status_code == 401 and c2.get("/parcelles").status_code == 200
    c3 = connecte("sam")
    assert c3.post("/auth/mot-de-passe", json={"ancien": "faux", "nouveau": "encore-un-mdp-1"}).status_code == 403
    assert c3.post("/auth/mot-de-passe", json={"ancien": MDP, "nouveau": "court"}).status_code == 422
    assert c3.post("/auth/mot-de-passe", json={"ancien": MDP, "nouveau": "encore-un-mdp-1"}).status_code == 204
    assert c3.get("/parcelles").status_code == 200 and c2.get("/parcelles").status_code == 401       # les autres sessions sont fermées
    assert anonyme().post("/auth/connexion", json={"identifiant": "sam", "mot_de_passe": "encore-un-mdp-1"}).status_code == 200
    with Session() as db:                                                                # expiration
        for s in db.scalars(select(SessionAuth)):
            s.expire_le = auth._maintenant() - timedelta(minutes=1)
        db.commit()
    assert c3.get("/parcelles").status_code == 401 and admin.get("/parcelles").status_code == 401


def test_mots_de_passe_hachés_et_admin_initial():
    h = auth.hacher("secret-123")
    assert h != auth.hacher("secret-123") and auth.verifier("secret-123", h) and not auth.verifier("secret-124", h)
    assert not auth.verifier("x", "format-invalide")


def test_page_daccueil_publique_et_configurable(ferme):
    c = anonyme()
    r = c.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "Ferme Emman Kabangu" in r.text and "Se connecter" in r.text
    assert "/tableau-de-bord/login.html" in r.text
    for page in ("logo.svg", "site.json", "marque.css"):                # ressources publiques de l'identité visuelle
        assert c.get(f"/tableau-de-bord/{page}").status_code == 200, page
    assert set(c.get("/tableau-de-bord/site.json").json()) >= {"demo", "lieu", "contact"}
    assert c.get("/parcelles").status_code == 401                           # la page publique n'ouvre l'accès à aucune donnée


# ---------- inscription depuis la page publique ----------
def demande(c=None, identifiant="nouveau.membre", mdp=MDP, nom="Nouveau Membre", email=None):
    email = email or f"{identifiant.replace(' ', '').replace('!', '')}@exemple.org"
    return (c or anonyme()).post("/auth/inscription", json={"identifiant": identifiant, "nom": nom, "mot_de_passe": mdp, "email": email})


@pytest.fixture()
def vierge(ferme):
    routeur_auth._demandes_ip.clear()
    return ferme


def test_inscription_n_ouvre_aucun_acces_avant_validation(vierge):
    admin, _ = vierge
    r = demande()
    assert r.status_code == 201 and "administrateur" in r.json()["message"]
    c = anonyme()
    assert c.get("/parcelles").status_code == 401
    mauvais = c.post("/auth/connexion", json={"identifiant": "nouveau.membre", "mot_de_passe": "faux-faux-faux"})
    attente = c.post("/auth/connexion", json={"identifiant": "nouveau.membre", "mot_de_passe": MDP})
    assert mauvais.status_code == 401                                              # un mauvais mot de passe ne révèle rien
    assert attente.status_code == 403 and "en attente" in attente.json()["detail"]
    assert [d["identifiant"] for d in admin.get("/auth/demandes").json()] == ["nouveau.membre"]
    assert "mdp_hash" not in admin.get("/auth/demandes").text and MDP not in admin.get("/auth/demandes").text


def test_l_admin_accepte_et_choisit_le_role(vierge):
    admin, _ = vierge
    demande()
    did = admin.get("/auth/demandes").json()[0]["id"]
    r = admin.post(f"/auth/demandes/{did}/accepter", json={"role": "operateur"})
    assert r.status_code == 201 and r.json()["role"] == "operateur"
    assert admin.get("/auth/demandes").json() == []
    c = connecte("nouveau.membre")                                                  # le mot de passe choisi à l'inscription fonctionne
    assert c.post("/parcelles/1/vanne", json={"action": "ouvrir", "duree_min": 10}).status_code == 200
    assert c.post("/plants", json=NOUVELLE).status_code == 403
    assert admin.post(f"/auth/demandes/{did}/accepter", json={"role": "admin"}).status_code == 404       # déjà traitée


def test_l_admin_refuse(vierge):
    admin, _ = vierge
    demande()
    did = admin.get("/auth/demandes").json()[0]["id"]
    assert admin.delete(f"/auth/demandes/{did}").status_code == 204
    assert anonyme().post("/auth/connexion", json={"identifiant": "nouveau.membre", "mot_de_passe": MDP}).status_code == 401
    assert demande().status_code == 201                                             # l'identifiant est de nouveau libre


def test_seul_l_admin_traite_les_demandes(vierge):
    admin, _ = vierge
    demande()
    did = admin.get("/auth/demandes").json()[0]["id"]
    compte(admin, "agathe", "agronome")
    c = connecte("agathe")
    assert c.get("/auth/demandes").status_code == 403
    assert c.post(f"/auth/demandes/{did}/accepter", json={"role": "admin"}).status_code == 403
    assert c.delete(f"/auth/demandes/{did}").status_code == 403
    assert anonyme().get("/auth/demandes").status_code == 401
    assert anonyme().post(f"/auth/demandes/{did}/accepter", json={"role": "admin"}).status_code == 401


def test_inscription_refuse_les_donnees_invalides_et_les_doublons(vierge):
    admin, _ = vierge
    assert demande(mdp="court").status_code == 422
    assert demande(identifiant="Mauvais Id!").status_code == 422
    assert demande(identifiant="ab").status_code == 422
    assert demande(identifiant="admin").status_code == 409                          # compte existant
    assert demande().status_code == 201 and demande(nom="Autre").status_code == 409  # déjà en attente
    r = anonyme().post("/auth/inscription", json={"identifiant": "avec.role", "nom": "Malin", "mot_de_passe": MDP, "role": "admin", "email": "malin@exemple.org"})
    assert r.status_code == 201                                                     # un rôle envoyé de force est ignoré
    did = [d["id"] for d in admin.get("/auth/demandes").json() if d["identifiant"] == "avec.role"][0]
    assert admin.post(f"/auth/demandes/{did}/accepter", json={}).json()["role"] == "lecteur"


def test_inscription_limitee_par_appareil_et_en_nombre(vierge, monkeypatch):
    for i in range(routeur_auth.DEMANDES_PAR_HEURE):
        assert demande(identifiant=f"membre{i}").status_code == 201
    r = demande(identifiant="trop.vite")
    assert r.status_code == 429 and "heure" in r.json()["detail"]
    routeur_auth._demandes_ip.clear()
    monkeypatch.setattr(routeur_auth, "DEMANDES_EN_ATTENTE_MAX", 5)
    assert demande(identifiant="en.trop").status_code == 503


def test_photos_du_diaporama(vierge, tmp_path, monkeypatch):
    from app import main
    c = anonyme()
    monkeypatch.setattr(main, "STATIC", tmp_path)
    assert c.get("/photos").json() == {"photos": []}                                 # pas de dossier : liste vide, pas d'erreur
    (tmp_path / "photos").mkdir()
    for nom in ("02-manioc.jpg", "01-maïs.JPG", "notes.txt", "tomate cerise.webp"):
        (tmp_path / "photos" / nom).write_bytes(b"x")
    liste = c.get("/photos").json()["photos"]
    assert [p["nom"] for p in liste] == ["Maïs", "Manioc", "Tomate cerise"]          # ordre par nom, numéro retiré, .txt ignoré
    assert liste[2]["url"] == "/tableau-de-bord/photos/tomate%20cerise.webp"
