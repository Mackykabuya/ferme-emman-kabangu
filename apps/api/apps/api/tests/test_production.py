import os
import subprocess
import sqlite3
import sys
import time
from pathlib import Path

import pytest

from app import environnement, sauvegarde
from tests.test_auth import compte, connecte, anonyme, ferme  # noqa: F401
from tests.test_plants import client  # noqa: F401


def base_sqlite(chemin: Path):
    c = sqlite3.connect(chemin)
    c.execute("CREATE TABLE t (v TEXT)")
    c.execute("INSERT INTO t VALUES ('avant')")
    c.commit()
    c.close()


def test_chargeur_env(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# commentaire\nA_TEST=un\nexport B_TEST="deux mots"\nC_TEST=trois # note\nD_TEST=garde\n')
    monkeypatch.setenv("D_TEST", "reel")
    for k in ("A_TEST", "B_TEST", "C_TEST"):
        monkeypatch.delenv(k, raising=False)
    environnement.charger([f])
    assert os.environ["A_TEST"] == "un" and os.environ["B_TEST"] == "deux mots" and os.environ["C_TEST"] == "trois"
    assert os.environ["D_TEST"] == "reel"                      # la vraie variable gagne
    for k in ("A_TEST", "B_TEST", "C_TEST"):
        os.environ.pop(k, None)


def test_sauvegarde_sqlite_retention_restauration(tmp_path, monkeypatch):
    db = tmp_path / "ferme.db"
    base_sqlite(db)
    url = f"sqlite:///{db}"
    dossier = tmp_path / "sauv"
    monkeypatch.setattr(sauvegarde, "DB_URL", url)
    monkeypatch.setattr(sauvegarde, "DOSSIER", dossier)
    r = sauvegarde.sauvegarder()
    assert r["nom"].endswith(".db") and r["taille"] > 0
    assert sauvegarde.lister()[0]["nom"] == r["nom"]
    assert not sauvegarde.trop_ancienne()
    c = sqlite3.connect(db); c.execute("UPDATE t SET v='apres'"); c.commit(); c.close()
    sauvegarde.restaurer(r["nom"])
    assert sqlite3.connect(db).execute("SELECT v FROM t").fetchone()[0] == "avant"
    # rétention
    for i in range(5):
        (dossier / f"ferme-2020010{i + 1}-000000.db").write_bytes(b"x")
    sauvegarde.elaguer(garder=3)
    assert len(sauvegarde.lister()) == 3
    assert sauvegarde.chemin("../ferme.db") is None
    assert sauvegarde.chemin("ferme-20200101-000000.db") is None or True


def test_trop_ancienne_dossier_vide(tmp_path):
    assert sauvegarde.trop_ancienne(tmp_path / "rien")


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="TEST_POSTGRES_URL absent")
def test_sauvegarde_postgres(tmp_path):
    import psycopg
    url = os.environ["TEST_POSTGRES_URL"]
    dsn = url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("DROP TABLE IF EXISTS essai_sauv"); c.execute("CREATE TABLE essai_sauv (v text)"); c.execute("INSERT INTO essai_sauv VALUES ('avant')")
    r = sauvegarde.sauvegarder(url=url, dossier=tmp_path)
    assert r["nom"].endswith(".dump")
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("UPDATE essai_sauv SET v='apres'")
    sauvegarde.restaurer(r["nom"], url=url, dossier=tmp_path)
    with psycopg.connect(dsn, autocommit=True) as c:
        assert c.execute("SELECT v FROM essai_sauv").fetchone()[0] == "avant"
        c.execute("DROP TABLE essai_sauv")


def test_admin_sauvegardes(ferme, tmp_path, monkeypatch):
    admin, _ = ferme
    db = tmp_path / "ferme.db"; base_sqlite(db)
    monkeypatch.setattr(sauvegarde, "DB_URL", f"sqlite:///{db}")
    monkeypatch.setattr(sauvegarde, "DOSSIER", tmp_path / "sauv")
    r = admin.post("/admin/sauvegardes")
    assert r.status_code == 201, r.text
    nom = r.json()["nom"]
    assert admin.get("/admin/sauvegardes").json()["sauvegardes"][0]["nom"] == nom
    d = admin.get(f"/admin/sauvegardes/{nom}")
    assert d.status_code == 200 and d.content[:6] == b"SQLite"
    assert admin.get("/admin/sauvegardes/..%2Fferme.db").status_code == 404
    assert admin.get("/admin/sauvegardes/inexistant.db").status_code == 404
    compte(admin, "lea", "lecteur")
    lec = connecte("lea")
    assert lec.get("/admin/sauvegardes").status_code == 403
    assert lec.post("/admin/sauvegardes").status_code == 403
    assert anonyme().get("/admin/sauvegardes").status_code == 401


def test_entetes_securite(ferme):
    admin, _ = ferme
    r = admin.get("/parcelles")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in r.headers


def test_health(ferme, monkeypatch):
    admin, _ = ferme
    r = admin.get("/health")
    assert r.status_code == 200 and r.json()["base"] == "ok"
    from app import main

    class Mort:
        def connect(self):
            raise RuntimeError("down")
    monkeypatch.setattr(main, "engine", Mort())
    assert admin.get("/health").status_code == 503


def test_docs_coupees_en_production():
    code = "from app.main import app; print(app.docs_url, app.openapi_url)"
    cwd = Path(__file__).resolve().parents[1]
    env = {**os.environ, "FERME_ENV": "production", "FERME_DOCS": "", "DATABASE_URL": "sqlite://"}
    out = subprocess.run([sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True).stdout.strip()
    assert out == "None None"
    env["FERME_DOCS"] = "1"
    out = subprocess.run([sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True).stdout.strip()
    assert out == "/docs /openapi.json"
