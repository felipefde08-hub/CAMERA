from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2_sha256${salt}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        _algo, salt, expected = stored_hash.split("$", 2)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt).split("$", 2)[2], expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _key() -> bytes:
    raw = os.getenv("CAMPEX_SECRET_KEY") or os.getenv("CAMPEX_CREDENTIAL_KEY") or "campex-dev-change-me"
    return hashlib.sha256(raw.encode()).digest()


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    key = _key()
    nonce = secrets.token_bytes(16)
    stream = hashlib.pbkdf2_hmac("sha256", key, nonce, 100_000, dklen=len(value.encode()))
    cipher = bytes(a ^ b for a, b in zip(value.encode(), stream))
    mac = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + mac + cipher).decode()


def decrypt_secret(payload: str | None) -> str | None:
    if not payload:
        return None
    raw = base64.urlsafe_b64decode(payload.encode())
    nonce, mac, cipher = raw[:16], raw[16:48], raw[48:]
    key = _key()
    expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("Credencial criptografada invalida.")
    stream = hashlib.pbkdf2_hmac("sha256", key, nonce, 100_000, dklen=len(cipher))
    return bytes(a ^ b for a, b in zip(cipher, stream)).decode()


def mask_sensitive_error(text: str | None) -> str | None:
    if not text:
        return text
    lowered = text.lower()
    if "rtsp://" in lowered or "rtsps://" in lowered or "password" in lowered or "senha" in lowered:
        return "Erro tecnico com detalhe sensivel ocultado."
    return text[:300]
