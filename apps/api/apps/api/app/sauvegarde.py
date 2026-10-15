"""
Sauvegardes de la base de données (comptes, parcelles, historique des mesures et des arrosages).

  SQLite     : copie cohérente du fichier (API de sauvegarde de SQLite, sans arrêter le serveur), vérifiée ensuite
  PostgreSQL : pg_dump au format « custom » (le programme pg_dump doit être installé ; il l'est dans l'image Docker)

Fichiers : ferme-AAAAMMJJ-HHMMSS.db (SQLite) ou .dump (PostgreSQL) dans le dossier SAUVEGARDES_DOSSIER
(par défaut apps/api/sauvegardes). Le serveur en fait une toutes les SAUVEGARDE_HEURES heures (24 ; 0 = jamais) et garde
les SAUVEGARDE_GARDER plus récentes (14). En ligne de commande, serveur arrêté pour la restauration :

  python -m app.sauvegarde sauvegarder
  python -m app.sauvegarde lister
  python -m app.sauvegarde restaurer ferme-20261011-020000.db
"""
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from .database import DB_URL

DOSSIER = Path(os.getenv("SAUVEGARDES_DOSSIER") or Path(__file__).resolve().parents[1] / "sauvegardes")
GARDER = int(os.getenv("SAUVEGARDE_GARDER", "14"))
HEURES = float(os.getenv("SAUVEGARDE_HEURES", "24"))
NOM_VALIDE = re.compile(r"^ferme-\d{8}-\d{6}\.(db|dump)$")


def _sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _fichier_sqlite(url: str) -> Path:
    chemin = make_url(url).database
    if not chemin or chemin == ":memory:":
        raise RuntimeError("La base SQLite est en mémoire : rien à sauvegarder.")
    return Path(chemin)


def _args_postgres(url: str) -> tuple[list[str], dict]:
    u = make_url(url)
    args = ["--host", u.host or "localhost", "--port", str(u.port or 5432), "--username", u.username or "postgres", "--dbname", u.database]
    return args, {**os.environ, **({"PGPASSWORD": u.password} if u.password else {})}


def _programme(nom: str) -> str:
    chemin = shutil.which(nom)
    if not chemin:
        raise RuntimeError(f"Le programme « {nom} » est introuvable : installez les outils client PostgreSQL (postgresql-client).")
    return chemin


def _nouveau_nom(dossier: Path, suffixe: str) -> str:
    t = datetime.now(timezone.utc).replace(microsecond=0)
    while (dossier / f"ferme-{t:%Y%m%d-%H%M%S}{suffixe}").exists():
        t += timedelta(seconds=1)
    return f"ferme-{t:%Y%m%d-%H%M%S}{suffixe}"


def sauvegarder(url: str | None = None, dossier: Path | None = None, garder: int | None = None) -> dict:
    """Crée une sauvegarde, la vérifie, supprime les plus anciennes. Retourne {nom, taille, date}."""
    url, dossier = url or DB_URL, Path(dossier or DOSSIER)
    dossier.mkdir(parents=True, exist_ok=True)
    nom = _nouveau_nom(dossier, ".db" if _sqlite(url) else ".dump")
    final, partiel = dossier / nom, dossier / (nom + ".partiel")
    try:
        if _sqlite(url):
            src = sqlite3.connect(f"file:{_fichier_sqlite(url)}?mode=ro", uri=True)
            dst = sqlite3.connect(partiel)
            try:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("La sauvegarde est corrompue (contrôle d'intégrité échoué).")
            finally:
                src.close()
                dst.close()
        else:
            args, env = _args_postgres(url)
            r = subprocess.run([_programme("pg_dump"), "--format=custom", "--no-owner", "--file", str(partiel), *args],
                               env=env, capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                raise RuntimeError("pg_dump a échoué : " + (r.stderr.strip().splitlines() or ["erreur inconnue"])[-1])
        os.replace(partiel, final)
    finally:
        partiel.unlink(missing_ok=True)
    elaguer(dossier, GARDER if garder is None else garder)
    return _fiche(final)


def _fiche(p: Path) -> dict:
    s = p.stat()
    return {"nom": p.name, "taille": s.st_size, "date": datetime.fromtimestamp(s.st_mtime, timezone.utc).replace(tzinfo=None).isoformat()}


def lister(dossier: Path | None = None) -> list[dict]:
    dossier = Path(dossier or DOSSIER)
    if not dossier.is_dir():
        return []
    return sorted((_fiche(p) for p in dossier.iterdir() if NOM_VALIDE.match(p.name)), key=lambda f: f["nom"], reverse=True)


def elaguer(dossier: Path | None = None, garder: int | None = None):
    dossier = Path(dossier or DOSSIER)
    for f in lister(dossier)[max(1, GARDER if garder is None else garder):]:
        (dossier / f["nom"]).unlink(missing_ok=True)


def chemin(nom: str, dossier: Path | None = None) -> Path | None:
    """Chemin d'une sauvegarde existante, ou None. Le nom est contrôlé : aucune sortie possible du dossier."""
    p = Path(dossier or DOSSIER) / nom
    return p if NOM_VALIDE.match(nom) and p.is_file() else None


def restaurer(nom: str, url: str | None = None, dossier: Path | None = None) -> str:
    """À faire serveur ARRÊTÉ. Une sauvegarde de l'état actuel est faite d'abord (au cas où on se tromperait de fichier)."""
    url, dossier = url or DB_URL, Path(dossier or DOSSIER)
    p = chemin(nom, dossier)
    if not p:
        raise FileNotFoundError(f"Sauvegarde introuvable : {nom}")
    if _sqlite(url) != (p.suffix == ".db"):
        raise RuntimeError("Ce fichier ne correspond pas au type de base utilisé (SQLite = .db, PostgreSQL = .dump).")
    cible_sqlite = _fichier_sqlite(url) if _sqlite(url) else None
    if cible_sqlite is None or cible_sqlite.exists():
        avant = sauvegarder(url, dossier)["nom"]
    else:
        avant = "(aucune : la base n'existait pas)"
    if _sqlite(url):
        verif = sqlite3.connect(p)
        try:
            if verif.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Cette sauvegarde est corrompue : restauration annulée.")
        finally:
            verif.close()
        for suffixe in ("-wal", "-shm"):
            Path(str(cible_sqlite) + suffixe).unlink(missing_ok=True)
        shutil.copyfile(p, cible_sqlite)
    else:
        args, env = _args_postgres(url)
        r = subprocess.run([_programme("pg_restore"), "--clean", "--if-exists", "--no-owner", *args, str(p)],
                           env=env, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            raise RuntimeError("pg_restore a échoué : " + (r.stderr.strip().splitlines() or ["erreur inconnue"])[-1])
    return avant


def trop_ancienne(dossier: Path | None = None, heures: float | None = None) -> bool:
    """Vrai s'il n'y a aucune sauvegarde, ou si la dernière date de plus de `heures` heures."""
    l = lister(dossier)
    if not l:
        return True
    derniere = datetime.fromisoformat(l[0]["date"])
    return datetime.now(timezone.utc).replace(tzinfo=None) - derniere > timedelta(hours=HEURES if heures is None else heures)


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "lister"
    try:
        if action == "sauvegarder":
            f = sauvegarder()
            print(f"Sauvegarde créée : {DOSSIER / f['nom']} ({f['taille'] // 1024} Ko)")
        elif action == "lister":
            for f in lister():
                print(f"{f['nom']}  {f['taille'] // 1024:>8} Ko  {f['date']} UTC")
            if not lister():
                print("Aucune sauvegarde.")
        elif action == "restaurer" and len(sys.argv) > 2:
            print("Restauration faite. État précédent conservé dans :", restaurer(sys.argv[2]))
        else:
            print(__doc__)
    except (RuntimeError, FileNotFoundError) as e:
        sys.exit(f"Erreur : {e}")
