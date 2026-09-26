"""
API layer for jobs: submit (returns immediately with a job id), poll, page results, cancel.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.connections import store
from apps.core.exceptions import Conflict, NotFound
from apps.engine.reader import ResultNotFound, ResultReader

from . import cancellation
from .models import Job
from .serializers import JobCreateSerializer, JobSerializer, ResultQuerySerializer
from .tasks import run_transform_job

logger = logging.getLogger(__name__)


@api_view(["GET", "POST"])
def job_collection(request):
    if request.method == "GET":
        jobs = Job.objects.all()[:50]
        return Response(JobSerializer(jobs, many=True).data)

    ser = JobCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data

    creds = store.load(data["connection_id"])  # raises CONNECTION_EXPIRED if gone
    store.touch(data["connection_id"])

    with transaction.atomic():
        job = Job.objects.create(
            connection_id=data["connection_id"],
            bucket=creds.bucket,
            file_key=data["file_key"],
            transform_type=data["transform_type"],
            prompt=data["prompt"],
            replacement=data.get("replacement", ""),
            columns=data["columns"],
            new_column_name=data.get("new_column_name", ""),
        )
        # Dispatch only after the row is committed so the worker can always find it.
        transaction.on_commit(lambda: _dispatch(job))

    logger.info("job %s queued (%s on %s)", job.id, job.transform_type, job.file_key)
    return Response({"job_id": str(job.id), "status": job.status}, status=status.HTTP_202_ACCEPTED)


def _dispatch(job: Job) -> None:
    result = run_transform_job.apply_async(args=[str(job.id)], task_id=str(job.id))
    Job.objects.filter(pk=job.pk).update(celery_task_id=result.id)


@api_view(["GET"])
def job_detail(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    return Response(JobSerializer(job).data)


@api_view(["POST"])
def job_cancel(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    if job.is_terminal:
        raise Conflict(f"Job is already {job.status}.")
    cancellation.request_cancel(str(job.id))
    if job.status == Job.Status.QUEUED:
        # The worker has not picked it up: mark it now; the task will exit immediately if it starts.
        Job.objects.filter(pk=job.pk, status=Job.Status.QUEUED).update(
            status=Job.Status.CANCELLED, stage=Job.Stage.DONE, finished_at=timezone.now()
        )
    job.refresh_from_db()
    return Response(JobSerializer(job).data)


@api_view(["GET"])
def job_result(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    if job.status != Job.Status.SUCCESS:
        raise Conflict(f"Result is not available: job is {job.status}.")
    q = ResultQuerySerializer(data=request.query_params)
    q.is_valid(raise_exception=True)
    params = q.validated_data
    try:
        reader = ResultReader(job.result_path)
    except ResultNotFound:
        raise NotFound("The result files for this job are no longer available.") from None
    page = reader.page(
        params["page"], params["page_size"], only_matched=params["only_matched"], total_rows=job.row_count
    )
    return Response(
        {
            "columns": page.columns,
            "rows": page.rows,
            "page": page.page,
            "page_size": page.page_size,
            "total_rows": page.total_rows,
            "total_pages": page.total_pages,
            "matched_rows": job.matched_rows,
        }
    )
