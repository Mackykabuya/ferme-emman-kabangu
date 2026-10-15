"""Lit un fichier « .env » (clé=valeur) s'il existe, sans dépendance. Les vraies variables d'environnement gardent la priorité.

Cherché dans apps/api/.env puis dans le dossier du projet. Exemple de ligne :  ADMIN_MOT_DE_PASSE=mon-mot-de-passe
"""
import os
from pathlib import Path


def lire(texte: str) -> dict[str, str]:
    sortie = {}
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.removeprefix("export ").partition("=")
        valeur = valeur.strip()
        if len(valeur) >= 2 and valeur[0] == valeur[-1] and valeur[0] in "\"'":
            valeur = valeur[1:-1]
        elif " #" in valeur:
            valeur = valeur.split(" #", 1)[0].rstrip()
        if cle.strip():
            sortie[cle.strip()] = valeur
    return sortie


def charger(chemins: list[Path] | None = None) -> list[Path]:
    """Retourne les fichiers lus. N'écrase jamais une variable déjà définie."""
    ici = Path(__file__).resolve()
    lus = []
    for p in chemins if chemins is not None else [ici.parents[1] / ".env", ici.parents[3] / ".env"]:
        if p.is_file():
            for cle, valeur in lire(p.read_text(encoding="utf-8")).items():
                os.environ.setdefault(cle, valeur)
            lus.append(p)
    return lus
