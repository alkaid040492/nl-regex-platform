"""
Celery task layer. Thin by design: resolve the Job, hand it to JobRunner, and decide
whether a transient failure should be retried.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from .models import Job
from .runner import JobRunner, RetryableFailure

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (10, 30, 60)


@shared_task(bind=True, name="jobs.run_transform_job", max_retries=MAX_RETRIES, acks_late=True)
def run_transform_job(self, job_id: str) -> dict:
    try:
        job = Job.objects.get(pk=job_id)
    except Job.DoesNotExist:
        logger.error("task received unknown job id %s", job_id)
        return {"job_id": job_id, "status": "MISSING"}

    try:
        job = JobRunner(job).run()
    except RetryableFailure as exc:
        attempt = self.request.retries
        if attempt >= MAX_RETRIES:
            Job.objects.filter(pk=job.pk).update(
                status=Job.Status.FAILED,
                stage=Job.Stage.DONE,
                error_code=exc.original.code,
                error_message=f"{exc.original.message} (gave up after {attempt} retries)",
                finished_at=timezone.now(),
            )
            return {"job_id": job_id, "status": Job.Status.FAILED}
        countdown = RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
        Job.objects.filter(pk=job.pk).update(
            status=Job.Status.QUEUED,
            error_code=exc.original.code,
            error_message=f"{exc.original.message} Retrying in {countdown}s (attempt {attempt + 1}/{MAX_RETRIES}).",
        )
        logger.warning("job %s transient failure (%s); retry %d in %ss", job_id, exc.original.code, attempt + 1, countdown)
        raise self.retry(exc=exc.original, countdown=countdown)

    return {"job_id": job_id, "status": job.status, "rows": job.row_count, "matched": job.matched_rows}
