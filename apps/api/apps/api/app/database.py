"""Connexion à la base. SQLite en développement (aucune installation) ; PostgreSQL en production via DATABASE_URL.

    DATABASE_URL=postgresql://ferme:motdepasse@db:5432/ferme      (le pilote psycopg est ajouté automatiquement)
"""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

SQLITE_PAR_DEFAUT = f"sqlite:///{Path(__file__).resolve().parents[1] / 'ferme.db'}"


def normaliser_url(url: str) -> str:
    """« postgres:// » et « postgresql:// » (formes courantes chez les hébergeurs) -> pilote psycopg 3."""
    for debut in ("postgres://", "postgresql://"):
        if url.startswith(debut):
            return "postgresql+psycopg://" + url[len(debut):]
    return url


DB_URL = normaliser_url(os.getenv("DATABASE_URL") or SQLITE_PAR_DEFAUT)
EST_SQLITE = DB_URL.startswith("sqlite")

if EST_SQLITE:
    engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
else:
    # pool_pre_ping : une connexion coupée (redémarrage de la base, réseau) est refaite au lieu de faire échouer la requête
    engine = create_engine(DB_URL, pool_pre_ping=True, pool_size=int(os.getenv("DB_POOL", "10")), max_overflow=5, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
