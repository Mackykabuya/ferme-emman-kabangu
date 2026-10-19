import os
import re
import secrets
import time
from datetime import timedelta
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import courriel, journal
from ..auth import (FAUX_HASH, _maintenant, LIBELLES, _empreinte, controler_mdp, exiger, fermer_sessions, hacher, jeton_courant,
                    ouvrir_session, utilisateur_courant, verifier)
from ..database import get_db
from ..models_auth import DemandeInscription, ReinitialisationMdp, Utilisateur

router = APIRouter(prefix="/auth", tags=["Connexion et comptes"])
Role = Literal["lecteur", "operateur", "agronome", "admin"]
ECHECS_MAX, BLOCAGE_S = 5, 300
_echecs: dict[str, list[float]] = {}          # identifiant -> horodatages (secondes) des échecs récents
_demandes_ip: dict[str, list[float]] = {}     # adresse -> horodatages des demandes d'inscription (anti-spam)
DEMANDES_PAR_HEURE, DEMANDES_EN_ATTENTE_MAX = 5, 100
_oublis_ip: dict[str, list[float]] = {}       # demandes « mot de passe oublié » par adresse
_oublis_mail: dict[str, list[float]] = {}     # … et par e-mail
OUBLIS_PAR_IP_HEURE, OUBLIS_PAR_MAIL_HEURE = 10, 3
REINIT_MINUTES = int(os.getenv("REINIT_MINUTES", "60"))
EMAIL_RE = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s.]{2,}")


def _email(valeur: str) -> str:
    mail = valeur.strip().lower()
    if len(mail) > 254 or not EMAIL_RE.fullmatch(mail):
        raise HTTPException(422, "Adresse e-mail invalide.")
    return mail


def _mail_pris(db: Session, mail: str, sauf_id: int | None = None) -> bool:
    q = select(Utilisateur.id).where(Utilisateur.email == mail)
    if sauf_id:
        q = q.where(Utilisateur.id != sauf_id)
    return bool(db.scalar(q) or db.scalar(select(DemandeInscription.id).where(DemandeInscription.email == mail)))


def _vue(u: Utilisateur) -> dict:
    return {"id": u.id, "identifiant": u.identifiant, "nom": u.nom, "role": u.role, "role_libelle": LIBELLES[u.role],
            "email": u.email, "actif": u.actif, "notif_alertes": bool(u.notif_alertes)}


class Connexion(BaseModel):
    identifiant: str = Field(min_length=1, max_length=254)       # identifiant OU adresse e-mail
    mot_de_passe: str = Field(min_length=1, max_length=200)


@router.post("/connexion")
def connexion(req: Connexion, request: Request, db: Session = Depends(get_db)):
    """Connexion par e-mail (ou identifiant) et mot de passe. Retourne un jeton à envoyer ensuite dans « Authorization: Bearer <jeton> »."""
    ident = req.identifiant.strip().lower()
    recents = [t for t in _echecs.get(ident, []) if time.time() - t < BLOCAGE_S]
    if len(recents) >= ECHECS_MAX:
        raise HTTPException(429, "Trop d'essais ratés. Patientez 5 minutes avant de réessayer.")
    par_mail = "@" in ident
    u = db.scalar(select(Utilisateur).where(Utilisateur.email == ident if par_mail else func.lower(Utilisateur.identifiant) == ident))
    d = None if u else db.scalar(select(DemandeInscription).where(DemandeInscription.email == ident if par_mail else DemandeInscription.identifiant == ident))
    ok = verifier(req.mot_de_passe, u.mdp_hash if u else d.mdp_hash if d else FAUX_HASH)
    if d and ok:                                  # bon mot de passe, mais le compte n'est pas encore validé
        raise HTTPException(403, "Votre demande d'inscription est en attente : un administrateur doit la valider avant votre première connexion.")
    if not (u and ok and u.actif):
        _echecs[ident] = [*recents, time.time()]
        journal.noter(db, None, "Connexion refusée", visiteur=ident[:60], detail="identifiant inconnu, mot de passe faux ou compte désactivé", ip=journal.adresse_ip(request))
        raise HTTPException(401, "E-mail ou mot de passe incorrect.")
    _echecs.pop(ident, None)
    jeton, fin = ouvrir_session(db, u)
    journal.noter(db, u, "Connexion", ip=journal.adresse_ip(request))
    return {"jeton": jeton, "expire_le": fin.isoformat(), "utilisateur": _vue(u)}


@router.get("/moi")
def moi(u: Utilisateur = Depends(utilisateur_courant)):
    return _vue(u)


@router.post("/deconnexion", status_code=204)
def deconnexion(jeton: str = Depends(jeton_courant), u: Utilisateur = Depends(utilisateur_courant), db: Session = Depends(get_db)):
    from ..models_auth import SessionAuth
    s = db.scalar(select(SessionAuth).where(SessionAuth.empreinte == _empreinte(jeton)))
    if s:
        db.delete(s)
        db.commit()


class ChangementMdp(BaseModel):
    ancien: str
    nouveau: str = Field(max_length=200)


@router.post("/mot-de-passe", status_code=204)
def changer_mdp(req: ChangementMdp, jeton: str = Depends(jeton_courant), u: Utilisateur = Depends(utilisateur_courant),
                db: Session = Depends(get_db)):
    """Change son propre mot de passe ; les autres sessions ouvertes sont fermées."""
    if not verifier(req.ancien, u.mdp_hash):
        raise HTTPException(403, "L'ancien mot de passe est incorrect.")
    controler_mdp(req.nouveau)
    u.mdp_hash = hacher(req.nouveau)
    fermer_sessions(db, u.id, sauf=_empreinte(jeton))
    db.commit()


class ChangementEmail(BaseModel):
    email: str = Field(max_length=254)
    mot_de_passe: str = Field(max_length=200)


@router.put("/moi/email")
def changer_email(req: ChangementEmail, u: Utilisateur = Depends(utilisateur_courant), db: Session = Depends(get_db)):
    """Définit ou change son propre e-mail (sert à la connexion et au « mot de passe oublié »)."""
    if not verifier(req.mot_de_passe, u.mdp_hash):
        raise HTTPException(403, "Mot de passe incorrect.")
    mail = _email(req.email)
    if _mail_pris(db, mail, u.id):
        raise HTTPException(409, "Cette adresse e-mail est déjà utilisée.")
    u.email = mail
    db.commit()
    return _vue(u)


class ChoixNotif(BaseModel):
    actif: bool


@router.put("/moi/notifications")
def changer_notifications(req: ChoixNotif, u: Utilisateur = Depends(utilisateur_courant), db: Session = Depends(get_db)):
    """Active ou coupe la réception des alertes par e-mail pour son propre compte."""
    u.notif_alertes = req.actif
    db.commit()
    return _vue(u)


# ---------- mot de passe oublié ----------
def _lien(jeton: str, base: str) -> str:
    return f"{base.rstrip('/')}/tableau-de-bord/reinitialiser.html#jeton={jeton}"


def _nouveau_jeton(db: Session, u: Utilisateur) -> str:
    """Un seul lien valable à la fois par utilisateur ; seule l'empreinte du jeton est gardée."""
    for r in db.scalars(select(ReinitialisationMdp).where(ReinitialisationMdp.utilisateur_id == u.id)):
        db.delete(r)
    jeton = secrets.token_urlsafe(32)
    db.add(ReinitialisationMdp(empreinte=_empreinte(jeton), utilisateur_id=u.id, expire_le=_maintenant() + timedelta(minutes=REINIT_MINUTES)))
    db.commit()
    return jeton


def _envoyer_lien(mail: str, nom: str, jeton: str):
    base = os.getenv("FERME_URL", "")
    if courriel.configure() and not base:
        print("FERME_URL n'est pas réglé : le lien n'est pas envoyé par e-mail (il serait forgeable). Réglez FERME_URL=http://adresse-du-serveur:8000")
    lien = _lien(jeton, base or "http://ADRESSE-DU-SERVEUR:8000")
    texte = (f"Bonjour {nom},\n\nPour choisir un nouveau mot de passe pour la Ferme Emman Kabangu, ouvrez ce lien "
             f"(valable {REINIT_MINUTES} minutes, utilisable une seule fois) :\n\n{lien}\n\n"
             "Si vous n'avez pas fait cette demande, ignorez ce message : votre mot de passe actuel reste valable.\n")
    if courriel.configure() and not base:
        print(f"[lien de réinitialisation pour {mail}] {lien}")
        return
    courriel.envoyer(mail, "Réinitialisation de votre mot de passe · Ferme Emman Kabangu", texte)


class Oubli(BaseModel):
    email: str = Field(max_length=254)


@router.post("/mot-de-passe-oublie")
def mot_de_passe_oublie(req: Oubli, request: Request, taches: BackgroundTasks, db: Session = Depends(get_db)):
    """Envoie un lien de réinitialisation. La réponse est toujours la même, que l'adresse existe ou non."""
    ip = request.client.host if request.client else "?"
    recents = [t for t in _oublis_ip.get(ip, []) if time.time() - t < 3600]
    if len(recents) >= OUBLIS_PAR_IP_HEURE:
        raise HTTPException(429, "Trop de demandes depuis cet appareil. Réessayez dans une heure.")
    _oublis_ip[ip] = [*recents, time.time()]
    mail = req.email.strip().lower()
    reponse = {"message": "Si cette adresse correspond à un compte, un lien de réinitialisation vient d'être envoyé. Pensez à vérifier vos courriers indésirables."}
    if not EMAIL_RE.fullmatch(mail):
        return reponse
    par_mail = [t for t in _oublis_mail.get(mail, []) if time.time() - t < 3600]
    if len(par_mail) >= OUBLIS_PAR_MAIL_HEURE:
        return reponse
    _oublis_mail[mail] = [*par_mail, time.time()]
    u = db.scalar(select(Utilisateur).where(Utilisateur.email == mail, Utilisateur.actif))
    if u:
        taches.add_task(_envoyer_lien, mail, u.nom, _nouveau_jeton(db, u))
    return reponse


class Reinitialisation(BaseModel):
    jeton: str = Field(min_length=10, max_length=200)
    nouveau: str = Field(max_length=200)


@router.post("/reinitialiser", status_code=204)
def reinitialiser(req: Reinitialisation, db: Session = Depends(get_db)):
    """Choisit un nouveau mot de passe avec le lien reçu. Le lien ne marche qu'une fois ; toutes les sessions sont fermées."""
    r = db.scalar(select(ReinitialisationMdp).where(ReinitialisationMdp.empreinte == _empreinte(req.jeton)))
    u = db.get(Utilisateur, r.utilisateur_id) if r else None
    if not r or r.expire_le < _maintenant() or not u or not u.actif:
        if r and r.expire_le < _maintenant():
            db.delete(r)
            db.commit()
        raise HTTPException(400, "Ce lien est invalide ou a expiré. Demandez-en un nouveau.")
    controler_mdp(req.nouveau)                          # mot de passe refusé : le lien reste utilisable
    u.mdp_hash = hacher(req.nouveau)
    db.delete(r)
    fermer_sessions(db, u.id)
    db.commit()
    for k in (u.identifiant.lower(), u.email or ""):
        _echecs.pop(k, None)


@router.post("/utilisateurs/{uid}/lien-reinitialisation")
def lien_reinitialisation(uid: int, request: Request, _: Utilisateur = Depends(exiger("admin")), db: Session = Depends(get_db)):
    """Pour un compte sans e-mail ou sans SMTP : l'administrateur obtient un lien à transmettre lui-même à la personne."""
    u = db.get(Utilisateur, uid)
    if not u or not u.actif:
        raise HTTPException(404, "Utilisateur introuvable ou désactivé.")
    base = os.getenv("FERME_URL") or str(request.base_url)
    return {"lien": _lien(_nouveau_jeton(db, u), base), "valable_minutes": REINIT_MINUTES}


# ---------- gestion des comptes (administrateur) ----------
class UtilisateurIn(BaseModel):
    identifiant: str = Field(min_length=3, max_length=40)
    nom: str = Field(min_length=2, max_length=80)
    role: Role
    mot_de_passe: str = Field(max_length=200)
    email: Optional[str] = Field(default=None, max_length=254)


class UtilisateurMaj(BaseModel):
    nom: Optional[str] = Field(default=None, min_length=2, max_length=80)
    role: Optional[Role] = None
    actif: Optional[bool] = None
    email: Optional[str] = Field(default=None, max_length=254)
    mot_de_passe: Optional[str] = Field(default=None, max_length=200)      # réinitialisation par l'administrateur


@router.get("/utilisateurs")
def lister(_: Utilisateur = Depends(exiger("admin")), db: Session = Depends(get_db)):
    return [_vue(u) for u in db.scalars(select(Utilisateur).order_by(Utilisateur.identifiant))]


@router.post("/utilisateurs", status_code=201)
def creer(req: UtilisateurIn, _: Utilisateur = Depends(exiger("admin")), db: Session = Depends(get_db)):
    ident = req.identifiant.strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", ident):
        raise HTTPException(422, "L'identifiant ne contient que des lettres minuscules, chiffres, point, tiret ou tiret bas.")
    controler_mdp(req.mot_de_passe)
    if db.scalar(select(Utilisateur.id).where(func.lower(Utilisateur.identifiant) == ident)):
        raise HTTPException(409, f"L'identifiant « {ident} » existe déjà.")
    mail = _email(req.email) if req.email and req.email.strip() else None
    if mail and _mail_pris(db, mail):
        raise HTTPException(409, "Cette adresse e-mail est déjà utilisée.")
    u = Utilisateur(identifiant=ident, nom=req.nom.strip(), role=req.role, mdp_hash=hacher(req.mot_de_passe), email=mail)
    db.add(u)
    db.commit()
    return _vue(u)


@router.put("/utilisateurs/{uid}")
def modifier(uid: int, req: UtilisateurMaj, moi: Utilisateur = Depends(exiger("admin")), db: Session = Depends(get_db)):
    u = db.get(Utilisateur, uid)
    if not u:
        raise HTTPException(404, "Utilisateur introuvable")
    ch = req.model_dump(exclude_unset=True)
    perd_admin = u.role == "admin" and u.actif and (ch.get("role", "admin") != "admin" or ch.get("actif", True) is False)
    if perd_admin and not db.scalar(select(Utilisateur.id).where(Utilisateur.role == "admin", Utilisateur.actif, Utilisateur.id != uid)):
        raise HTTPException(409, "Il doit rester au moins un administrateur actif.")
    if u.id == moi.id and ch.get("actif") is False:
        raise HTTPException(409, "Vous ne pouvez pas désactiver votre propre compte.")
    if "email" in ch:
        mail = _email(ch["email"]) if ch["email"] and ch["email"].strip() else None
        if mail and _mail_pris(db, mail, uid):
            raise HTTPException(409, "Cette adresse e-mail est déjà utilisée.")
        ch["email"] = mail
    mdp = ch.pop("mot_de_passe", None)
    if mdp is not None:
        controler_mdp(mdp)
        u.mdp_hash = hacher(mdp)
        fermer_sessions(db, u.id)
    for k, v in ch.items():
        setattr(u, k, v)
    if ch.get("actif") is False:
        fermer_sessions(db, u.id)
    db.commit()
    return _vue(u)


# ---------- inscription depuis la page publique ----------
class Inscription(BaseModel):
    email: str = Field(max_length=254)
    nom: str = Field(min_length=2, max_length=80)
    mot_de_passe: str = Field(max_length=200)
    identifiant: Optional[str] = Field(default=None, max_length=40)      # facultatif : déduit de l'e-mail sinon


def _identifiant_libre(db: Session, mail: str) -> str:
    base = re.sub(r"[^a-z0-9._-]", "", mail.split("@")[0]) or "membre"
    base = (base.ljust(3, "0"))[:34]            # 3 caractères minimum, 34 maximum (de la place pour un numéro)
    ident, n = base, 1
    while (db.scalar(select(Utilisateur.id).where(func.lower(Utilisateur.identifiant) == ident))
           or db.scalar(select(DemandeInscription.id).where(DemandeInscription.identifiant == ident))):
        n += 1
        ident = f"{base}{n}"
    return ident


def _identifiant_valide(ident: str):
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", ident):
        raise HTTPException(422, "L'identifiant ne contient que des lettres minuscules, chiffres, point, tiret ou tiret bas (3 caractères minimum).")


@router.post("/inscription", status_code=201)
def inscription(req: Inscription, request: Request, db: Session = Depends(get_db)):
    """Demande de compte. Rien n'est accessible avant la validation par un administrateur, qui choisit le rôle."""
    ip = request.client.host if request.client else "?"
    recents = [t for t in _demandes_ip.get(ip, []) if time.time() - t < 3600]
    if len(recents) >= DEMANDES_PAR_HEURE:
        raise HTTPException(429, "Trop de demandes depuis cet appareil. Réessayez dans une heure.")
    mail = _email(req.email)
    controler_mdp(req.mot_de_passe)
    if db.scalar(select(func.count()).select_from(DemandeInscription)) >= DEMANDES_EN_ATTENTE_MAX:
        raise HTTPException(503, "Trop de demandes en attente. Contactez directement l'administrateur de la ferme.")
    if _mail_pris(db, mail):
        raise HTTPException(409, "Cette adresse e-mail est déjà utilisée. Connectez-vous, ou utilisez « Mot de passe oublié ».")
    if req.identifiant and req.identifiant.strip():
        ident = req.identifiant.strip().lower()
        _identifiant_valide(ident)
        if (db.scalar(select(Utilisateur.id).where(func.lower(Utilisateur.identifiant) == ident))
                or db.scalar(select(DemandeInscription.id).where(DemandeInscription.identifiant == ident))):
            raise HTTPException(409, "Cet identifiant est déjà pris. Choisissez-en un autre.")
    else:
        ident = _identifiant_libre(db, mail)
    db.add(DemandeInscription(identifiant=ident, nom=req.nom.strip(), mdp_hash=hacher(req.mot_de_passe), email=mail))
    db.commit()
    _demandes_ip[ip] = [*recents, time.time()]
    return {"message": "Demande envoyée. Un administrateur doit la valider avant votre première connexion."}


class Acceptation(BaseModel):
    role: Role = "lecteur"


@router.get("/demandes")
def demandes(_: Utilisateur = Depends(exiger("admin")), db: Session = Depends(get_db)):
    return [{"id": d.id, "identifiant": d.identifiant, "nom": d.nom, "email": d.email, "cree_le": d.cree_le.isoformat()}
            for d in db.scalars(select(DemandeInscription).order_by(DemandeInscription.id))]


@router.post("/demandes/{did}/accepter", status_code=201)
def accepter(did: int, req: Acceptation, _: Utilisateur = Depends(exiger("admin")), db: Session = Depends(get_db)):
    d = db.get(DemandeInscription, did)
    if not d:
        raise HTTPException(404, "Demande introuvable (déjà traitée ?)")
    if db.scalar(select(Utilisateur.id).where(func.lower(Utilisateur.identifiant) == d.identifiant)):
        db.delete(d)
        db.commit()
        raise HTTPException(409, "Un compte avec cet identifiant existe déjà ; la demande a été supprimée.")
    u = Utilisateur(identifiant=d.identifiant, nom=d.nom, role=req.role, mdp_hash=d.mdp_hash, email=d.email)
    db.add(u)
    db.delete(d)
    db.commit()
    return _vue(u)


@router.delete("/demandes/{did}", status_code=204)
def refuser(did: int, _: Utilisateur = Depends(exiger("admin")), db: Session = Depends(get_db)):
    d = db.get(DemandeInscription, did)
    if d:
        db.delete(d)
        db.commit()
