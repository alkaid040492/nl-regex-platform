"""
Redis cache for LLM results so identical prompts are never sent twice.

Key = sha256(transform_type | normalized prompt | sorted columns). Sample values are
deliberately NOT part of the key: they only add context, and including them would make
the cache useless across files with the same intent.
"""
from __future__ import annotations

import hashlib
import json
import re

from django.conf import settings

from apps.core.redis import get_redis

from .schemas import RegexSpec

_PREFIX = "llm:regex:"
HITS_KEY = "metrics:llm_cache_hits"
MISSES_KEY = "metrics:llm_cache_misses"


def normalize_prompt(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt.strip().lower())


def cache_key(transform_type: str, prompt: str) -> str:
    payload = f"{transform_type}|{normalize_prompt(prompt)}"
    return _PREFIX + hashlib.sha256(payload.encode()).hexdigest()


def get(transform_type: str, prompt: str) -> RegexSpec | None:
    r = get_redis()
    raw = r.get(cache_key(transform_type, prompt))
    if raw is None:
        r.incr(MISSES_KEY)
        return None
    r.incr(HITS_KEY)
    return RegexSpec.from_dict(json.loads(raw), cached=True)


def put(transform_type: str, prompt: str, spec: RegexSpec) -> None:
    get_redis().set(cache_key(transform_type, prompt), json.dumps(spec.to_dict()), ex=settings.LLM_CACHE_TTL_SECONDS)


def invalidate(transform_type: str, prompt: str) -> None:
    get_redis().delete(cache_key(transform_type, prompt))
