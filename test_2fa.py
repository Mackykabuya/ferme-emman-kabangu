import base64
import re
import time

from app import totp
from tests.test_auth import MDP, anonyme, compte, connecte, ferme  # noqa: F401
from tests.test_plants import client  # noqa: F401


def code_actuel(secret, decalage=0):
    return totp._code(secret, totp.pas_courant() + decalage)


def activer(c):
    r = c.post("/auth/moi/2fa/preparer")
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    assert r.json()["uri"].startswith("otpauth://totp/") and secret in r.json()["uri"]
    r = c.post("/auth/moi/2fa/activer", json={"code": code_actuel(secret)})
    assert r.status_code == 200, r.text
    return secret, r.json()["codes_secours"]


def test_vecteur_rfc6238():
    s = base64.b32encode(b"12345678901234567890").decode()
    assert totp._code(s, 59 // 30) == "287082"
    assert totp._code(s, 1111111109 // 30) == "081804"
    assert totp.verifier(s, "287082", maintenant=59) == 1
    assert totp.verifier(s, "287082", dernier_pas=1, maintenant=59) is None      # rejeu refusé
    assert totp.verifier(s, "12345", maintenant=59) is None
    assert totp.verifier(s, "abcdef", maintenant=59) is None


def test_activation_puis_connexion_en_deux_temps(ferme):
    admin, _ = ferme
    compte(admin, "agro", "agronome")
    c = connecte("agro")
    assert c.get("/auth/moi").json()["double_authentification"] is False
    secret, secours = activer(c)
    assert len(secours) == 8 and all(re.fullmatch(r"[a-z2-9]{5}-[a-z2-9]{5}", x) for x in secours)
    assert c.get("/auth/moi").json()["double_authentification"] is True

    a = anonyme()
    r = a.post("/auth/connexion", json={"identifiant": "agro", "mot_de_passe": MDP})
    assert r.status_code == 200 and r.json() == {"code_requis": True}            # pas de jeton sans code
    # le code de l'activation vient d'être consommé : il est refusé (rejeu) ; le suivant passe
    r = a.post("/auth/connexion", json={"identifiant": "agro", "mot_de_passe": MDP, "code": code_actuel(secret)})
    assert r.status_code == 401
    r = a.post("/auth/connexion", json={"identifiant": "agro", "mot_de_passe": MDP, "code": code_actuel(secret, 1)})
    assert r.status_code == 200 and r.json()["jeton"]
    # mauvais mot de passe : jamais de « code_requis »
    assert a.post("/auth/connexion", json={"identifiant": "agro", "mot_de_passe": "faux", "code": "000000"}).status_code == 401


def test_activation_exige_un_bon_code(ferme):
    admin, _ = ferme
    compte(admin, "oper", "operateur")
    c = connecte("oper")
    assert c.post("/auth/moi/2fa/activer", json={"code": "123456"}).status_code == 409      # pas de secret encore
    c.post("/auth/moi/2fa/preparer")
    assert c.post("/auth/moi/2fa/activer", json={"code": "000000"}).status_code == 422
    assert c.get("/auth/moi").json()["double_authentification"] is False


def test_code_de_secours_usage_unique(ferme):
    admin, _ = ferme
    compte(admin, "agro", "agronome")
    c = connecte("agro")
    _, secours = activer(c)
    a = anonyme()
    r = a.post("/auth/connexion", json={"identifiant": "agro", "mot_de_passe": MDP, "code": secours[0]})
    assert r.status_code == 200 and r.json()["jeton"]
    r = a.post("/auth/connexion", json={"identifiant": "agro", "mot_de_passe": MDP, "code": secours[0].upper().replace("-", " ")})
    assert r.status_code == 401                                                     # déjà consommé
    r = a.post("/auth/connexion", json={"identifiant": "agro", "mot_de_passe": MDP, "code": secours[1].upper()})
    assert r.status_code == 200                                                     # casse et tiret sans importance
    assert c.get("/auth/moi/2fa").json()["codes_secours_restants"] == 6


def test_blocage_apres_codes_faux(ferme):
    admin, _ = ferme
    compte(admin, "agro", "agronome")
    activer(connecte("agro"))
    a = anonyme()
    for _ in range(5):
        assert a.post("/auth/connexion", json={"identifiant": "agro", "mot_de_passe": MDP, "code": "000000"}).status_code == 401
    assert a.post("/auth/connexion", json={"identifiant": "agro", "mot_de_passe": MDP, "code": "000000"}).status_code == 429


def test_desactivation_demande_mdp_et_code(ferme):
    admin, _ = ferme
    compte(admin, "agro", "agronome")
    c = connecte("agro")
    secret, _ = activer(c)
    assert c.post("/auth/moi/2fa/desactiver", json={"mot_de_passe": "faux", "code": code_actuel(secret, 1)}).status_code == 403
    assert c.post("/auth/moi/2fa/desactiver", json={"mot_de_passe": MDP, "code": "000000"}).status_code == 403
    assert c.post("/auth/moi/2fa/desactiver", json={"mot_de_passe": MDP, "code": code_actuel(secret, 1)}).status_code == 204
    assert anonyme().post("/auth/connexion", json={"identifiant": "agro", "mot_de_passe": MDP}).json().get("jeton")
    assert c.get("/auth/moi/2fa").json() == {"actif": False, "codes_secours_restants": 0}


def test_renouvellement_des_codes_de_secours(ferme):
    admin, _ = ferme
    compte(admin, "agro", "agronome")
    c = connecte("agro")
    secret, anciens = activer(c)
    r = c.post("/auth/moi/2fa/codes-secours", json={"mot_de_passe": MDP, "code": code_actuel(secret, 1)})
    assert r.status_code == 200
    nouveaux = r.json()["codes_secours"]
    assert len(nouveaux) == 8 and not set(nouveaux) & set(anciens)
    assert anonyme().post("/auth/connexion", json={"identifiant": "agro", "mot_de_passe": MDP, "code": anciens[0]}).status_code == 401


def test_reinitialisation_par_admin(ferme):
    admin, _ = ferme
    u = compte(admin, "agro", "agronome")
    c = connecte("agro")
    activer(c)
    assert c.delete(f"/auth/utilisateurs/{u['id']}/2fa").status_code == 403         # réservé aux administrateurs
    assert admin.delete(f"/auth/utilisateurs/{u['id']}/2fa").status_code == 204
    assert admin.delete("/auth/utilisateurs/99999/2fa").status_code == 404
    assert c.get("/auth/moi").status_code == 401                                    # ses sessions sont fermées
    assert anonyme().post("/auth/connexion", json={"identifiant": "agro", "mot_de_passe": MDP}).json().get("jeton")
    assert admin.get("/auth/utilisateurs").json()  # la liste reste lisible


def test_migration_ajoute_les_colonnes_2fa():
    from app.migration import COLONNES
    assert {("utilisateurs", "totp_secret", "VARCHAR(64)"), ("utilisateurs", "totp_actif", "BOOLEAN DEFAULT FALSE"),
            ("utilisateurs", "totp_dernier", "INTEGER DEFAULT 0")} <= set(COLONNES)
