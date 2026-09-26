"""Symmetric encryption for credentials at rest (Fernet / AES-128-CBC + HMAC)."""
from __future__ import annotations

import json
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings.FERNET_KEY
    if not key or key.startswith("REPLACE_ME"):
        raise RuntimeError("FERNET_KEY is not configured. Generate one with Fernet.generate_key().")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_dict(data: dict) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode())


def decrypt_dict(token: bytes | str) -> dict:
    if isinstance(token, str):
        token = token.encode()
    try:
        return json.loads(_fernet().decrypt(token))
    except InvalidToken as exc:
        raise ValueError("Ciphertext is invalid or was encrypted with a different key") from exc
