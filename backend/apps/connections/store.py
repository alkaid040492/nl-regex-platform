"""
Encrypted, short-lived credential store backed by Redis.

Credentials never touch Postgres or logs. They are Fernet-encrypted with the server key,
stored under a random UUID with a TTL, and decrypted only inside the process that needs
them (API handler or Celery worker).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone

from django.conf import settings

from apps.core.crypto import decrypt_dict, encrypt_dict
from apps.core.redis import get_redis

from .exceptions import ConnectionExpired

_KEY_PREFIX = "conn:"


@dataclass(frozen=True)
class S3Credentials:
    access_key: str
    secret_key: str
    bucket: str
    region: str
    endpoint_url: str | None = None

    @property
    def access_key_hint(self) -> str:
        return f"****{self.access_key[-4:]}" if len(self.access_key) >= 4 else "****"

    def __repr__(self) -> str:  # never leak the secret in tracebacks / logs
        return f"S3Credentials(bucket={self.bucket!r}, access_key={self.access_key_hint}, region={self.region!r})"


def save(creds: S3Credentials) -> tuple[str, datetime]:
    connection_id = str(uuid.uuid4())
    ttl = settings.CONNECTION_TTL_SECONDS
    get_redis().set(_KEY_PREFIX + connection_id, encrypt_dict(asdict(creds)), ex=ttl)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    return connection_id, expires_at


def load(connection_id: str) -> S3Credentials:
    raw = get_redis().get(_KEY_PREFIX + str(connection_id))
    if raw is None:
        raise ConnectionExpired("This S3 connection has expired or does not exist. Please connect again.")
    return S3Credentials(**decrypt_dict(raw))


def touch(connection_id: str) -> None:
    """Extend the TTL on use so an active session does not expire mid-work."""
    get_redis().expire(_KEY_PREFIX + str(connection_id), settings.CONNECTION_TTL_SECONDS)


def delete(connection_id: str) -> None:
    get_redis().delete(_KEY_PREFIX + str(connection_id))
