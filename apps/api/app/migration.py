"""Petites évolutions de la base existante : create_all() crée les tables manquantes mais n'ajoute pas de colonne
à une table déjà là. Ici on ajoute (une seule fois, sans rien perdre) les colonnes apparues depuis."""
from sqlalchemy import inspect, text

COLONNES = [("utilisateurs", "email", "VARCHAR(254)"), ("demandes_inscription", "email", "VARCHAR(254)"),
            ("parcelles", "latitude", "FLOAT"), ("parcelles", "longitude", "FLOAT"),
            ("utilisateurs", "notif_alertes", "BOOLEAN DEFAULT TRUE")]
INDEX = [("ix_utilisateurs_email_unique", "utilisateurs", "email")]


def appliquer(engine) -> list[str]:
    fait = []
    insp = inspect(engine)
    with engine.begin() as c:
        for table, col, typ in COLONNES:
            if insp.has_table(table) and col not in {x["name"] for x in insp.get_columns(table)}:
                c.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))
                fait.append(f"{table}.{col}")
        for nom, table, col in INDEX:
            c.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {nom} ON {table} ({col})"))
    return fait
