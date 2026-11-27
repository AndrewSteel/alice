"""Decryption of the IMAP passwords of alice.imap_mailboxes. Same format and key as alice-mail-reader
(AES-256-CBC, key = SHA-256 of MAIL_ENC_KEY, "<iv hex>:<ciphertext hex>"). There is no second
password store; plaintext passwords only live in memory and never appear in logs or errors (AK-55)."""
from __future__ import annotations

import hashlib

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


class DecryptError(Exception):
    """The stored password cannot be decrypted (wrong key or damaged value). No details on purpose."""


def _key(secret: str) -> bytes:
    if not secret:
        raise DecryptError("MAIL_ENC_KEY ist nicht gesetzt")
    return hashlib.sha256(secret.encode()).digest()


def decrypt_password(password_enc: str, secret: str) -> str:
    try:
        iv_hex, enc_hex = password_enc.split(":")
        cipher = AES.new(_key(secret), AES.MODE_CBC, bytes.fromhex(iv_hex))
        return unpad(cipher.decrypt(bytes.fromhex(enc_hex)), 16).decode("utf-8")
    except DecryptError:
        raise
    except Exception:
        raise DecryptError("Passwort kann nicht entschlüsselt werden (Schlüssel passt nicht)") from None


def encrypt_password(plaintext: str, secret: str, iv: bytes) -> str:
    """Only for tests: the same format alice-mail-reader writes."""
    cipher = AES.new(_key(secret), AES.MODE_CBC, iv)
    return iv.hex() + ":" + cipher.encrypt(pad(plaintext.encode("utf-8"), 16)).hex()
