"""Alertes par e-mail. Toutes les NOTIF_MINUTES (5 par défaut ; 0 = désactivé), les alertes de la ferme sont relues ;
les destinataires (comptes actifs avec e-mail, rôle ≥ NOTIF_ROLE_MIN, case « recevoir les alertes » cochée) reçoivent UN
message regroupant les alertes NOUVELLES. Une alerte déjà annoncée n'est pas renvoyée tant qu'elle dure, sauf rappel toutes
les NOTIF_RAPPEL_H heures (12 par défaut, 0 = jamais). Une fois résolue puis réapparue, elle est annoncée de nouveau.
Sans SMTP_HOTE, rien n'est envoyé ni mémorisé (les alertes restent visibles dans l'application)."""
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import courriel
from .auth import NIVEAUX
from .models_auth import AlerteNotifiee, Utilisateur
from .routers.alertes import toutes_les_alertes

MINUTES = float(os.getenv("NOTIF_MINUTES", "5"))
RAPPEL_H = float(os.getenv("NOTIF_RAPPEL_H", "12"))
ROLE_MIN = os.getenv("NOTIF_ROLE_MIN", "agronome")
GRAVITES = {"critique": "URGENT", "attention": "À vérifier"}


def _reel() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)      # temps réel, même quand la simulation accélère l'horloge


def destinataires(db: Session) -> list[Utilisateur]:
    mini = NIVEAUX.get(ROLE_MIN, 3)
    return [u for u in db.scalars(select(Utilisateur).where(Utilisateur.actif.is_(True), Utilisateur.notif_alertes.is_(True),
                                                              Utilisateur.email.is_not(None)))
            if NIVEAUX[u.role] >= mini]


def _message(alertes: list[dict]) -> tuple[str, str]:
    urgentes = sum(a["gravite"] == "critique" for a in alertes)
    sujet = f"Ferme Emman Kabangu : {len(alertes)} alerte{'s' if len(alertes) > 1 else ''}" + (f" dont {urgentes} urgente{'s' if urgentes > 1 else ''}" if urgentes else "")
    lignes = ["Bonjour,", "", "La ferme signale :", ""]
    for a in alertes:
        lignes += [f"[{GRAVITES[a['gravite']]}] {a['titre']} · {a['parcelle']}", f"  {a['message']}", f"  À faire : {a['conseil']}", ""]
    base = os.getenv("FERME_URL", "").rstrip("/")
    if base:
        lignes.append(f"Voir les parcelles : {base}/tableau-de-bord/parcelles.html")
    lignes += ["", "Pour ne plus recevoir ces e-mails : Mon compte > Alertes par e-mail."]
    return sujet, "\n".join(lignes)


def traiter(db: Session, envoyer=courriel.envoyer) -> dict:
    """Une vérification. Retourne un petit bilan (utile aux tests et au journal)."""
    actives = {f"{a['code']}:{a['parcelle_id']}": a for a in toutes_les_alertes(db) if a["gravite"] in GRAVITES}
    connues = {n.cle: n for n in db.scalars(select(AlerteNotifiee))}
    for cle in set(connues) - set(actives):                       # alertes résolues : on les oublie
        db.delete(connues.pop(cle))
    limite = _reel() - timedelta(hours=RAPPEL_H) if RAPPEL_H > 0 else None
    a_dire = [c for c in actives if c not in connues or (limite and connues[c].notifiee_le < limite)]
    db.commit()
    if not a_dire or not courriel.configure():
        return {"actives": len(actives), "a_annoncer": len(a_dire), "envoyes": 0}
    dest = destinataires(db)
    if not dest:
        return {"actives": len(actives), "a_annoncer": len(a_dire), "envoyes": 0}
    sujet, texte = _message(sorted((actives[c] for c in a_dire), key=lambda a: (a["gravite"] != "critique", a["parcelle"])))
    envoyes = sum(bool(envoyer(u.email, sujet, texte)) for u in dest)
    if envoyes:                                                    # si personne n'a pu être joint, on réessaiera au prochain tour
        for c in a_dire:
            if c in connues:
                connues[c].notifiee_le = _reel()
            else:
                db.add(AlerteNotifiee(cle=c))
        db.commit()
    return {"actives": len(actives), "a_annoncer": len(a_dire), "envoyes": envoyes}
