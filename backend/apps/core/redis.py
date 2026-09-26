"""Shared Redis client for application data (db 2): credentials, LLM cache, progress, metrics."""
from __future__ import annotations

from functools import lru_cache

import redis
from django.conf import settings


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.APP_REDIS_URL, decode_responses=False, socket_timeout=5)
