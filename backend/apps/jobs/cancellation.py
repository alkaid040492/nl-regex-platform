"""
Cooperative cancellation via a Redis flag.

The worker runs with --pool=solo (one Spark driver per process), where Celery's
revoke(terminate=True) is not available. Instead the API sets a flag; the runner checks it
between stages, and during the long Spark stage a monitor thread cancels the Spark job
group, which aborts the running action within a few seconds.
"""
from __future__ import annotations

from apps.core.redis import get_redis

_PREFIX = "job:cancel:"
_TTL = 24 * 3600


def request_cancel(job_id: str) -> None:
    get_redis().set(_PREFIX + job_id, b"1", ex=_TTL)


def is_cancel_requested(job_id: str) -> bool:
    return get_redis().exists(_PREFIX + job_id) == 1


def clear(job_id: str) -> None:
    get_redis().delete(_PREFIX + job_id)


class JobCancelled(Exception):
    pass
