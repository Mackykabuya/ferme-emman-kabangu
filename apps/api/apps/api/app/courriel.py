"""Envoi d'e-mails par SMTP. Sans SMTP_HOTE, rien n'est envoyé : le message est écrit dans le journal du serveur
(pratique à la maison ; l'administrateur peut aussi générer un lien de réinitialisation depuis la page Comptes)."""
import os
import smtplib
import ssl
from email.message import EmailMessage


def configure() -> bool:
    return bool(os.getenv("SMTP_HOTE"))


def envoyer(a: str, sujet: str, texte: str) -> bool:
    """True si le message est parti ; False (et message dans le journal) si SMTP n'est pas réglé ou en cas d'échec."""
    if not configure():
        print(f"[e-mail non envoyé : SMTP_HOTE absent] À : {a} · {sujet}\n{texte}")
        return False
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
