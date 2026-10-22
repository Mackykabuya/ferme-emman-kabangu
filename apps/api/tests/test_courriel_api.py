import io
import json
import urllib.error

import pytest

from app import courriel


class Reponse:
    def __init__(self, status=201):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _propre(monkeypatch):
    for k in ("SMTP_HOTE", "SMTP_UTILISATEUR", "SMTP_DE", "EMAIL_API", "EMAIL_API_CLE", "EMAIL_DE"):
        monkeypatch.delenv(k, raising=False)


def espion(monkeypatch, reponse=None, erreur=None):
    vus = []

    def faux(req, timeout=0, context=None):
        vus.append(req)
        if erreur:
            raise erreur
        return reponse or Reponse()
    monkeypatch.setattr("urllib.request.urlopen", faux)
    return vus


def test_brevo(monkeypatch):
    monkeypatch.setenv("EMAIL_API", "Brevo")
    monkeypatch.setenv("EMAIL_API_CLE", "cle-secrete")
    monkeypatch.setenv("EMAIL_DE", "Ferme <ferme@exemple.org>")
    vus = espion(monkeypatch)
    assert courriel.configure() and courriel.envoyer("a@b.org", "Sujet é", "Corps") is True
    r = vus[0]
    assert r.full_url == "https://api.brevo.com/v3/smtp/email" and r.get_header("Api-key") == "cle-secrete"
    c = json.loads(r.data)
    assert c == {"sender": {"name": "Ferme", "email": "ferme@exemple.org"}, "to": [{"email": "a@b.org"}], "subject": "Sujet é", "textContent": "Corps"}


def test_resend(monkeypatch):
    monkeypatch.setenv("EMAIL_API", "resend")
    monkeypatch.setenv("EMAIL_API_CLE", "re_123")
    monkeypatch.setenv("EMAIL_DE", "ferme@exemple.org")
    vus = espion(monkeypatch)
    assert courriel.envoyer("a@b.org", "S", "C") is True
    r = vus[0]
    assert r.full_url == "https://api.resend.com/emails" and r.get_header("Authorization") == "Bearer re_123"
    assert json.loads(r.data) == {"from": "Ferme Emman Kabangu <ferme@exemple.org>", "to": ["a@b.org"], "subject": "S", "text": "C"}


def test_api_prioritaire_sur_smtp(monkeypatch):
    monkeypatch.setenv("SMTP_HOTE", "smtp.invalide.test")
    monkeypatch.setenv("EMAIL_API", "brevo")
    monkeypatch.setenv("EMAIL_API_CLE", "k")
    monkeypatch.setenv("EMAIL_DE", "f@exemple.org")
    vus = espion(monkeypatch)
    assert courriel.envoyer("a@b.org", "S", "C") is True and len(vus) == 1


def test_echecs_renvoient_false_sans_planter(monkeypatch, capsys):
    monkeypatch.setenv("EMAIL_API", "brevo")
    monkeypatch.setenv("EMAIL_API_CLE", "mauvaise")
    monkeypatch.setenv("EMAIL_DE", "f@exemple.org")
    espion(monkeypatch, erreur=urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b'{"message":"Key not found"}')))
    assert courriel.envoyer("a@b.org", "S", "C") is False
    sortie = capsys.readouterr().out
    assert "HTTP 401" in sortie and "mauvaise" not in sortie                  # la clé n'est jamais écrite dans les journaux
    espion(monkeypatch, erreur=OSError("réseau coupé"))
    assert courriel.envoyer("a@b.org", "S", "C") is False


def test_expediteur_obligatoire_et_cle_obligatoire(monkeypatch):
    monkeypatch.setenv("EMAIL_API", "brevo")
    assert not courriel.configure()                              # clé absente : l'API n'est pas considérée comme réglée
    monkeypatch.setenv("EMAIL_API_CLE", "k")
    vus = espion(monkeypatch)
    assert courriel.configure() and courriel.envoyer("a@b.org", "S", "C") is False and vus == []   # pas d'expéditeur


def test_api_inconnue_ignoree(monkeypatch):
    monkeypatch.setenv("EMAIL_API", "inconnue")
    monkeypatch.setenv("EMAIL_API_CLE", "k")
    assert not courriel.configure()
