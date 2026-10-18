import re
from pathlib import Path

import pytest
from PIL import Image

from tests.test_parcelles import ferme  # noqa: F401
from tests.test_plants import client  # noqa: F401

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
PAGES = ["accueil", "login", "inscription", "mot-de-passe-oublie", "reinitialiser", "parcelles", "catalogue", "index", "compte", "carte"]


def test_manifest_valide_et_icones_presentes(ferme):  # noqa: F811
    r = ferme.get("/tableau-de-bord/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    m = r.json()
    assert m["display"] == "standalone" and m["scope"] == "/tableau-de-bord/" and m["start_url"].startswith(m["scope"]) and m["lang"] == "fr"
    tailles = {(i["sizes"], i["purpose"]) for i in m["icons"]}
    assert ("192x192", "any") in tailles and ("512x512", "any") in tailles and ("512x512", "maskable") in tailles
    for i in m["icons"]:
        assert ferme.get(i["src"]).status_code == 200
        assert Image.open(STATIC / Path(i["src"]).name).size == tuple(map(int, i["sizes"].split("x")))


@pytest.mark.parametrize("page", PAGES)
def test_chaque_page_declare_l_application(page):
    html = (STATIC / f"{page}.html").read_text(encoding="utf8")
    assert 'href="/tableau-de-bord/manifest.webmanifest"' in html and 'src="/tableau-de-bord/pwa.js"' in html and 'name="theme-color"' in html


def test_service_worker_ne_garde_jamais_les_donnees_de_l_api(ferme):  # noqa: F811
    r = ferme.get("/tableau-de-bord/sw.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    sw = r.text
    assert "startsWith(CHEMIN)" in sw and 'r.method !== "GET"' in sw                  # seuls les fichiers de l'interface, en GET
    coquille = re.search(r"const COQUILLE = \[(.*?)\]\.map", sw, re.S).group(1)
    for fichier in re.findall(r'"([^"]+)"', coquille):                                   # tout ce qui est pré-chargé existe bien
        assert (STATIC / fichier).exists(), fichier
    assert not re.search(r'"/', coquille)                                         # aucun chemin absolu : jamais l'API (/parcelles, /auth…)
    assert ferme.get("/tableau-de-bord/offline.html").status_code == 200
