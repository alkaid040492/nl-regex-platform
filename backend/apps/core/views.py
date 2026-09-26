"""Health and metrics endpoints."""
from __future__ import annotations

import logging

from django.db import connection
from django.db.models import Avg, Count, F
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.core.redis import get_redis
from apps.jobs.models import Job

logger = logging.getLogger(__name__)


def _check(fn) -> str:
    try:
        fn()
        return "ok"
    except Exception as exc:  # report, never raise: health must always answer
        logger.warning("health check failed: %s", exc)
        return "error"


def _check_db() -> None:
    with connection.cursor() as cur:
        cur.execute("SELECT 1")


def _check_redis() -> None:
    get_redis().ping()


def _check_worker() -> None:
    """Ping the worker; a busy solo worker cannot answer, so fall back to its heartbeat."""
    from config.celery import app

    replies = app.control.ping(timeout=2.0)
    if replies:
        return
    from apps.jobs.progress import HEARTBEAT_KEY

    if get_redis().get(HEARTBEAT_KEY):
        return  # worker is alive but busy with a job
    raise RuntimeError("no celery worker replied and no recent heartbeat")


@api_view(["GET"])
def health(request):
    checks = {
        "db": _check(_check_db),
        "redis": _check(_check_redis),
        "worker": _check(_check_worker),
    }
    status_code = 200 if checks["db"] == "ok" and checks["redis"] == "ok" else 503
    return Response({"status": "ok" if status_code == 200 else "degraded", **checks}, status=status_code)


@api_view(["GET"])
def metrics_summary(request):
    by_status = {row["status"]: row["n"] for row in Job.objects.values("status").annotate(n=Count("id"))}
    finished = Job.objects.filter(status=Job.Status.SUCCESS, started_at__isnull=False, finished_at__isnull=False)
    avg_duration = finished.annotate(d=F("finished_at") - F("started_at")).aggregate(avg=Avg("d"))["avg"]
    rows_processed = Job.objects.filter(status=Job.Status.SUCCESS).aggregate(total=Count("row_count"))

    r = get_redis()
    cache_hits = int(r.get("metrics:llm_cache_hits") or 0)
    cache_misses = int(r.get("metrics:llm_cache_misses") or 0)

    return Response(
        {
            "jobs_by_status": {s.value: by_status.get(s.value, 0) for s in Job.Status},
            "avg_success_duration_seconds": avg_duration.total_seconds() if avg_duration else None,
            "rows_processed_total": Job.objects.filter(status=Job.Status.SUCCESS)
            .aggregate(total=Count("row_count"))["total"],
            "llm_cache": {"hits": cache_hits, "misses": cache_misses},
        }
    )
