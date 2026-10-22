"""Envoi d'e-mails. Deux façons, au choix :

  - SMTP (SMTP_HOTE, SMTP_PORT, SMTP_UTILISATEUR, SMTP_MOT_DE_PASSE, SMTP_DE) : à la maison ou sur un serveur normal ;
  - API web en HTTPS (EMAIL_API=brevo ou resend, EMAIL_API_CLE, EMAIL_DE) : pour les hébergeurs qui bloquent le SMTP
    (Render gratuit bloque les ports 25, 465 et 587). Utilisée en priorité si elle est réglée.

Sans aucun des deux, rien n'est envoyé : le message est écrit dans le journal du serveur (pratique à la maison ;
l'administrateur peut aussi générer un lien de réinitialisation depuis la page Comptes)."""
import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import parseaddr

API = {"brevo": "https://api.brevo.com/v3/smtp/email", "resend": "https://api.resend.com/emails"}


def _api() -> str:
    nom = (os.getenv("EMAIL_API") or "").strip().lower()
    return nom if nom in API and os.getenv("EMAIL_API_CLE") else ""


def configure() -> bool:
    return bool(_api() or os.getenv("SMTP_HOTE"))


def _envoyer_api(nom: str, a: str, sujet: str, texte: str) -> bool:
    de = os.getenv("EMAIL_DE") or os.getenv("SMTP_DE") or os.getenv("SMTP_UTILISATEUR") or ""
    titre, adresse = parseaddr(de)
    if not adresse:
        print("Envoi d'e-mail en échec : EMAIL_DE (adresse de l'expéditeur) est absent.")
        return False
    titre = titre or "Ferme Emman Kabangu"
    cle = os.environ["EMAIL_API_CLE"]
    if nom == "brevo":
        corps = {"sender": {"name": titre, "email": adresse}, "to": [{"email": a}], "subject": sujet, "textContent": texte}
        entetes = {"api-key": cle}
    else:
        corps = {"from": f"{titre} <{adresse}>", "to": [a], "subject": sujet, "text": texte}
        entetes = {"Authorization": f"Bearer {cle}"}
    req = urllib.request.Request(API[nom], data=json.dumps(corps).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          "User-Agent": "ferme-emman-kabangu", **entetes})
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl.create_default_context()) as r:
            return 200 <= r.status < 300
    except urllib.error.HTTPError as e:
        print(f"Envoi d'e-mail en échec ({nom}) : HTTP {e.code} {e.read()[:300].decode(errors='replace')}")
    except Exception as e:
        print(f"Envoi d'e-mail en échec ({nom}) :", e)
    return False


def envoyer(a: str, sujet: str, texte: str) -> bool:
    """True si le message est parti ; False (et message dans le journal) si SMTP n'est pas réglé ou en cas d'échec."""
    if not configure():
        print(f"[e-mail non envoyé : ni SMTP_HOTE ni EMAIL_API réglés] À : {a} · {sujet}\n{texte}")
        return False
    if _api():
        return _envoyer_api(_api(), a, sujet, texte)
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_DE") or os.getenv("SMTP_UTILISATEUR") or "ferme@localhost"
    msg["To"], msg["Subject"] = a, sujet
    msg.set_content(texte)
    hote, port = os.environ["SMTP_HOTE"], int(os.getenv("SMTP_PORT", "587"))
    try:
        if os.getenv("SMTP_SSL") == "1":
            s = smtplib.SMTP_SSL(hote, port, timeout=15, context=ssl.create_default_context())
        else:
            s = smtplib.SMTP(hote, port, timeout=15)
            if os.getenv("SMTP_STARTTLS", "1") != "0":
                s.starttls(context=ssl.create_default_context())
        with s:
            if os.getenv("SMTP_UTILISATEUR"):
                s.login(os.environ["SMTP_UTILISATEUR"], os.getenv("SMTP_MOT_DE_PASSE", ""))
            s.send_message(msg)
        return True
    except Exception as e:
        print("Envoi d'e-mail en échec :", e)
        return False
