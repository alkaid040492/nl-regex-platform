"""
Job: one asynchronous transformation run. The row is the single source of truth for
status/progress that the API exposes; the Celery task updates it as it moves through stages.
"""
from __future__ import annotations

import uuid

from django.db import models


class Job(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        SUCCESS = "SUCCESS"
        FAILED = "FAILED"
        CANCELLED = "CANCELLED"

    class Stage(models.TextChoices):
        PENDING = "PENDING"
        LOAD = "LOAD"
        LLM = "LLM"
        VALIDATE = "VALIDATE"
        TRANSFORM = "TRANSFORM"
        WRITE = "WRITE"
        DONE = "DONE"

    class TransformType(models.TextChoices):
        REPLACE = "REPLACE", "Find pattern and replace with a fixed value"
        EXTRACT = "EXTRACT", "Extract the matched pattern into a new column"
        NORMALIZE = "NORMALIZE", "Rewrite matches into a normalized format"

    TERMINAL_STATUSES = frozenset({"SUCCESS", "FAILED", "CANCELLED"})

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # lifecycle
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True)
    stage = models.CharField(max_length=16, choices=Stage.choices, default=Stage.PENDING)
    progress = models.PositiveSmallIntegerField(default=0)
    celery_task_id = models.CharField(max_length=64, blank=True, default="")

    # input (never store the credentials themselves; connection_id points at encrypted Redis entry)
    connection_id = models.UUIDField()
    bucket = models.CharField(max_length=255)
    file_key = models.CharField(max_length=1024)
    transform_type = models.CharField(max_length=16, choices=TransformType.choices)
    prompt = models.TextField()
    replacement = models.TextField(blank=True, default="")
    columns = models.JSONField(default=list)
    new_column_name = models.CharField(max_length=255, blank=True, default="")

    # llm output
    regex_pattern = models.TextField(blank=True, default="")
    replacement_template = models.TextField(blank=True, default="")
    llm_explanation = models.TextField(blank=True, default="")
    llm_cache_hit = models.BooleanField(default=False)

    # result
    row_count = models.BigIntegerField(null=True, blank=True)
    matched_rows = models.BigIntegerField(null=True, blank=True)
    result_path = models.CharField(max_length=1024, blank=True, default="")
    result_columns = models.JSONField(default=list, blank=True)
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_message = models.TextField(blank=True, default="")

    # timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Job {self.id} [{self.status}]"

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
