import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, SessionLocal, engine
from . import ajouts, migration, notifications, simulation, sauvegarde
from sqlalchemy import text
from .auth import creer_admin_initial, email_admin_depuis_env, exiger
from .routers import admin, alertes, rapports as rapports_api, auth as auth_api, decision, eau, diagnostic, irrigation, meteo, parcelles, plants
from .routers import simulation as simulation_api
from .seed import seed_catalogue
from .seed_parcelles import seed_parcelles


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    for c in migration.appliquer(engine):
        print("Base mise à jour : colonne ajoutée", c)
    with SessionLocal() as db:
        n = seed_catalogue(db)
        if n:
            print(f"Catalogue initialisé : {n} plantes")
        if seed_parcelles(db):
            print("10 parcelles de démonstration créées")
        nouveaux = ajouts.appliquer(db)
        if nouveaux:
            print("Ajouté :", ", ".join(nouveaux))
        cree = creer_admin_initial(db)
        email_admin_depuis_env(db)
        if cree:
            print("=" * 60)
            print(f"Compte administrateur créé : identifiant « {cree[0]} » · mot de passe « {cree[1]} »")
            print("Notez-le maintenant, il ne sera plus affiché. Changez-le après la première connexion.")
            print("=" * 60)
    if simulation.SECONDES > 0:
        simulation.initialiser()
    minutes = float(os.getenv("PLANIFICATION_MINUTES", "15"))     # 0 = pas de passe automatique

    async def boucle():
        while True:
            await asyncio.sleep(minutes * 60)
            try:
                await asyncio.to_thread(parcelles.planifier)
            except Exception as e:
                print("Passe automatique en échec :", e)

    tache = asyncio.create_task(boucle()) if minutes > 0 else None
    min_meteo = float(os.getenv("METEO_MINUTES", "30"))           # 0 = pas de météo réelle automatique

    async def boucle_meteo():
        while True:
            try:
                await asyncio.to_thread(meteo.actualiser_auto)
            except Exception as e:
                print("Météo réelle indisponible :", e)
            await asyncio.sleep(min_meteo * 60)

    tache_meteo = asyncio.create_task(boucle_meteo()) if min_meteo > 0 else None

    async def boucle_simulation():
        while True:
            await asyncio.sleep(simulation.SECONDES)
            if simulation.actif():
                try:
                    await asyncio.to_thread(simulation.avancer)
                except Exception as e:
                    print("Simulation en échec :", e)

    tache_sim = asyncio.create_task(boucle_simulation()) if simulation.SECONDES > 0 else None
    if tache_sim:
        print(f"Simulation des capteurs active : le temps passe {round(simulation.PAS_MIN * 60 / simulation.SECONDES)} fois plus vite "
              "(SIMULATION_SECONDES=0 pour la désactiver)")

    async def boucle_sauvegarde():
        await asyncio.sleep(60)
        while True:
            try:
                if await asyncio.to_thread(sauvegarde.trop_ancienne):
                    r = await asyncio.to_thread(sauvegarde.sauvegarder)
                    print("Sauvegarde automatique :", r["nom"])
            except Exception as e:
                print("Sauvegarde automatique en échec :", e)
            await asyncio.sleep(3600)

    tache_sauv = asyncio.create_task(boucle_sauvegarde()) if sauvegarde.HEURES > 0 else None
    def _verifier_alertes():
        with SessionLocal() as db:
            return notifications.traiter(db)

    async def boucle_notifications():
        await asyncio.sleep(90)
        while True:
            try:
                r = await asyncio.to_thread(_verifier_alertes)
                if r["envoyes"]:
                    print(f"Alertes par e-mail : {r['a_annoncer']} nouvelle(s), {r['envoyes']} message(s) envoyé(s)")
            except Exception as e:
                print("Notification des alertes en échec :", e)
            await asyncio.sleep(max(30, notifications.MINUTES * 60))

    tache_notif = asyncio.create_task(boucle_notifications()) if notifications.MINUTES > 0 else None
    yield
    for t in (tache, tache_meteo, tache_sim, tache_sauv, tache_notif):
        if t:
            t.cancel()


PRODUCTION = os.getenv("FERME_ENV", "").lower() == "production"
DOCS = (not PRODUCTION) or os.getenv("FERME_DOCS") == "1"
app = FastAPI(title="Ferme Emman Kabangu - API", version="0.2.0", lifespan=lifespan,
              docs_url="/docs" if DOCS else None, redoc_url="/redoc" if DOCS else None,
              openapi_url="/openapi.json" if DOCS else None)


@app.middleware("http")
async def en_tetes_securite(request: Request, call_next):
    rep = await call_next(request)
    rep.headers.setdefault("X-Content-Type-Options", "nosniff")
    rep.headers.setdefault("X-Frame-Options", "DENY")
    rep.headers.setdefault("Referrer-Policy", "same-origin")
    rep.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(self)")
    if os.getenv("FERME_HTTPS") == "1":
        rep.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    chemin = request.url.path
    if not chemin.startswith("/tableau-de-bord") and chemin != "/":
        rep.headers.setdefault("Cache-Control", "no-store")
    return rep


app.include_router(plants.router, dependencies=[Depends(exiger("lecteur"))])
app.include_router(irrigation.router, dependencies=[Depends(exiger("lecteur"))])
app.include_router(diagnostic.router, dependencies=[Depends(exiger("lecteur"))])
app.include_router(decision.router, dependencies=[Depends(exiger("lecteur"))])
app.include_router(parcelles.router, dependencies=[Depends(exiger("lecteur"))])
app.include_router(meteo.router, dependencies=[Depends(exiger("lecteur"))])
app.include_router(alertes.router, dependencies=[Depends(exiger("lecteur"))])
app.include_router(eau.router, dependencies=[Depends(exiger("lecteur"))])
app.include_router(rapports_api.router, dependencies=[Depends(exiger("lecteur"))])
app.include_router(simulation_api.router, dependencies=[Depends(exiger("lecteur"))])
app.include_router(auth_api.router)
app.include_router(admin.router)


STATIC = Path(__file__).parent / "static"
EXT_PHOTOS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


@app.get("/photos", tags=["Système"])
def photos():
    """Photos du dossier static/photos pour le fond qui défile (publique). Le nom du fichier devient la légende :
    « 02-manioc.jpg » s'affiche « Manioc » (le numéro sert seulement à choisir l'ordre)."""
    import re
    from urllib.parse import quote
    dossier = STATIC / "photos"
    fichiers = sorted((f for f in dossier.iterdir() if f.suffix.lower() in EXT_PHOTOS), key=lambda f: f.name.lower()) if dossier.is_dir() else []
    sortie = []
    for f in fichiers[:30]:
        sans_ext = re.sub(r"(\.(jpe?g|png|webp|avif))+$", "", f.name, flags=re.I)        # « ananas.jpg.jpg » (extension doublée sous Windows) -> « ananas »
        nom = re.sub(r"^\d+[-_ .]*", "", sans_ext).replace("-", " ").replace("_", " ").strip() or sans_ext
        sortie.append({"url": "/tableau-de-bord/photos/" + quote(f.name), "nom": nom[:1].upper() + nom[1:]})
    return {"photos": sortie}
if STATIC.exists():  # interface web servie par l'API elle-même : aucune installation en plus
    app.mount("/tableau-de-bord", StaticFiles(directory=STATIC, html=True), name="tableau-de-bord")

    @app.get("/", include_in_schema=False)
    def accueil():
        return FileResponse(STATIC / "accueil.html")      # page publique : présentation de la ferme et bouton de connexion


@app.get("/health", tags=["Système"])
def health():
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        base = "ok"
    except Exception:
        return JSONResponse({"status": "erreur", "base": "indisponible"}, status_code=503)
    return {"status": "ok", "base": base, "simulation": simulation.SECONDES > 0}
