"""Double authentification par code à usage court (TOTP, RFC 6238) : celui des applications Google Authenticator, Microsoft
Authenticator, Authy, FreeOTP… Aucune bibliothèque externe : HMAC-SHA1, 30 secondes, 6 chiffres.
Les codes de secours (à garder hors de l'ordinateur) servent si le téléphone est perdu : chacun ne marche qu'une fois."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

PAS_S, CHIFFRES, FENETRE = 30, 6, 1            # ±30 s de tolérance sur l'heure du téléphone
NB_CODES_SECOURS = 8
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"        # sans i, l, o, 0, 1 : on les confond à la lecture


def nouveau_secret() -> str:
    """Secret de 160 bits en base 32 (32 caractères), à saisir ou à scanner dans l'application."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, pas: int) -> str:
    cle = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    h = hmac.new(cle, struct.pack(">Q", pas), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** CHIFFRES).zfill(CHIFFRES)


def pas_courant(maintenant: float | None = None) -> int:
    return int((time.time() if maintenant is None else maintenant) // PAS_S)


def verifier(secret: str, code: str, dernier_pas: int = 0, maintenant: float | None = None) -> int | None:
    """Retourne le pas (période de 30 s) du code s'il est bon ET plus récent que le dernier code accepté (un code ne
    sert qu'une fois, même s'il est encore valide), sinon None."""
    code = "".join(code.split())
    if not (code.isdigit() and len(code) == CHIFFRES):
        return None
    t, trouve = pas_courant(maintenant), None
    for pas in range(t - FENETRE, t + FENETRE + 1):
        if hmac.compare_digest(_code(secret, pas), code) and pas > dernier_pas:
            trouve = pas
    return trouve


def uri(secret: str, compte: str, emetteur: str = "Ferme Emman Kabangu") -> str:
    """Adresse « otpauth:// » que lit le code QR (ou à saisir à la main : seul le secret compte)."""
    return f"otpauth://totp/{quote(emetteur)}:{quote(compte)}?secret={secret}&issuer={quote(emetteur)}&algorithm=SHA1&digits={CHIFFRES}&period={PAS_S}"


def nouveaux_codes_secours() -> list[str]:
    return ["".join(secrets.choice(_ALPHABET) for _ in range(10)) for _ in range(NB_CODES_SECOURS)]


def normaliser_secours(code: str) -> str:
    return "".join(c for c in code.lower() if c.isalnum())


def empreinte_secours(code: str) -> str:
    return hashlib.sha256(normaliser_secours(code).encode()).hexdigest()


def afficher_secours(code: str) -> str:
    return f"{code[:5]}-{code[5:]}"


def groupes(secret: str) -> str:
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
