from tests.test_auth import MDP, anonyme, compte, connecte, ferme  # noqa: F401
from tests.test_plants import client  # noqa: F401


def journal(admin, **filtres):
    r = admin.get("/admin/journal", params=filtres)
    assert r.status_code == 200, r.text
    return r.json()


def test_vanne_ouverte_et_fermee_sont_notees_avec_qui_quoi_et_duree(ferme):  # noqa: F811
    admin, _ = ferme
    p = admin.get("/parcelles").json()[0]
    assert admin.post(f"/parcelles/{p['id']}/vanne", json={"action": "ouvrir", "duree_min": 30}).status_code == 200
    assert admin.post(f"/parcelles/{p['id']}/vanne", json={"action": "fermer"}).status_code == 200
    a = journal(admin)["actions"]
    assert [x["action"] for x in a[:2]] == ["Vanne fermée", "Vanne ouverte"]
    ouv = a[1]
    assert ouv["cible"] == p["nom"] and ouv["detail"] == "ouverte 30 min" and ouv["utilisateur"] == "admin" and ouv["role"] == "admin"
    assert len(ouv["quand"]) == 19                                           # JJ/MM/AAAA HH:MM:SS


def test_lectures_mesures_de_capteur_et_actions_refusees_ne_sont_pas_notees(ferme):  # noqa: F811
    admin, _ = ferme
    compte(admin, "lecteur1", "lecteur")
    p = admin.get("/parcelles").json()[0]
    avant = journal(admin)["total"]
    admin.get("/parcelles"); admin.get("/alertes"); admin.get("/eau")
    assert admin.put(f"/parcelles/{p['id']}", json={"mesures": {"humidite_sol_pct": 41.0}}).status_code == 200      # capteur
    lecteur = connecte("lecteur1")
    assert lecteur.post(f"/parcelles/{p['id']}/vanne", json={"action": "ouvrir", "duree_min": 10}).status_code == 403   # refusé
    assert journal(admin)["total"] == avant + 1                              # seule la connexion du lecteur s'ajoute


def test_parcelle_creee_modifiee_supprimee(ferme):  # noqa: F811
    admin, _ = ferme
    pid = admin.post("/parcelles", json={"nom": "Parcelle Z9", "surface_m2": 900, "plant_id": 2}).json()["id"]
    assert admin.put(f"/parcelles/{pid}", json={"stade": "Floraison", "mode": "manuel"}).status_code == 200
    assert admin.delete(f"/parcelles/{pid}").status_code == 204
    a = journal(admin)["actions"][:3]
    assert [(x["action"], x["cible"]) for x in a] == [("Parcelle supprimée", "Parcelle Z9"), ("Parcelle modifiée", "Parcelle Z9"), ("Parcelle créée", "Parcelle Z9")]
    assert a[1]["detail"] == "Modifié : mode, stade"


def test_connexions_reussies_et_refusees_sans_mot_de_passe(ferme):  # noqa: F811
    admin, _ = ferme
    compte(admin, "agro1", "agronome")
    connecte("agro1")
    c = anonyme()
    assert c.post("/auth/connexion", json={"identifiant": "agro1", "mot_de_passe": "mauvais-mot-de-passe-secret"}).status_code == 401
    a = journal(admin)["actions"]
    assert [(x["action"], x["utilisateur"]) for x in a[:3]] == [("Connexion refusée", "agro1"), ("Connexion", "agro1"), ("Compte créé", "admin")]
    texte = str(a)
    assert "mauvais-mot-de-passe-secret" not in texte and MDP not in texte and "Bearer" not in texte


def test_filtres_pagination_et_droits(ferme):  # noqa: F811
    admin, _ = ferme
    compte(admin, "lecteur2", "lecteur")
    p = admin.get("/parcelles").json()[0]
    for _ in range(3):
        admin.post(f"/parcelles/{p['id']}/vanne", json={"action": "ouvrir", "duree_min": 5})
    connecte("lecteur2")
    assert journal(admin, utilisateur="lecteur2")["total"] == 1
    assert journal(admin, q="vanne")["total"] == 3 and journal(admin, q="VANNE ouverte")["total"] == 3
    assert journal(admin, jours=1)["total"] == journal(admin)["total"]
    page = journal(admin, limite=2, debut=1)
    assert len(page["actions"]) == 2 and page["actions"][0]["id"] == journal(admin)["actions"][1]["id"]
    lecteur = connecte("lecteur2")
    assert lecteur.get("/admin/journal").status_code == 403
    assert anonyme().get("/admin/journal").status_code == 401


def test_actions_de_comptes_et_de_simulation(ferme):  # noqa: F811
    admin, _ = ferme
    u = compte(admin, "oper1", "operateur")
    assert admin.put(f"/auth/utilisateurs/{u['id']}", json={"actif": False}).status_code == 200
    a = journal(admin)["actions"]
    assert (a[0]["action"], a[0]["cible"]) == ("Compte modifié", "oper1") and (a[1]["action"], a[1]["cible"]) == ("Compte créé", "")


def test_page_du_journal_servie_avec_ses_filtres_et_l_export(ferme):  # noqa: F811
    admin, _ = ferme
    html = admin.get("/tableau-de-bord/journal.html").text
    assert "/admin/journal" in html and 'id="f_jours"' in html and 'id="csv"' in html and "langues.js" in html
    assert 'href="journal.html"' in admin.get("/tableau-de-bord/compte.html").text
