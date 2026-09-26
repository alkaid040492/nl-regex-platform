"""
Progress reporting for a running job.

* ProgressReporter writes stage/progress to the Job row (throttled) and a worker heartbeat
  to Redis, so the API can show liveness even while the solo worker is busy.
* SparkStageMonitor is a background thread that maps Spark's own task-completion counters
  (via SparkContext.statusTracker) onto a progress range while an action runs, and cancels
  the job group if the user asked to cancel.
"""
from __future__ import annotations

import logging
import threading
import time

from django.utils import timezone
from pyspark.sql import SparkSession

from apps.core.redis import get_redis

from . import cancellation
from .models import Job

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "worker:heartbeat"
HEARTBEAT_TTL = 90


class ProgressReporter:
    def __init__(self, job: Job, min_interval: float = 0.5):
        self.job = job
        self._min_interval = min_interval
        self._last_write = 0.0
        self._last_progress = -1

    def set_stage(self, stage: str, progress: int, **fields) -> None:
        self._write(stage=stage, progress=progress, force=True, **fields)

    def set_progress(self, progress: int) -> None:
        self._write(progress=progress)

    def _write(self, *, force: bool = False, **fields) -> None:
        now = time.monotonic()
        progress = fields.get("progress")
        if not force and progress is not None:
            if progress == self._last_progress or now - self._last_write < self._min_interval:
                return
        if progress is not None:
            fields["progress"] = max(0, min(100, int(progress)))
            self._last_progress = fields["progress"]
        Job.objects.filter(pk=self.job.pk).update(**fields)
        self._last_write = now
        try:
            get_redis().set(HEARTBEAT_KEY, timezone.now().isoformat(), ex=HEARTBEAT_TTL)
        except Exception:  # heartbeat is best-effort
            pass


class SparkStageMonitor:
    """
    Context manager: while active, polls Spark's status tracker and reports progress in
    [start, end]. Also polls the cancel flag and aborts the job group when it is set.
    """

    def __init__(self, spark: SparkSession, reporter: ProgressReporter, job_id: str, start: int, end: int, poll: float = 1.5):
        self.spark = spark
        self.reporter = reporter
        self.job_id = job_id
        self.start, self.end = start, end
        self.poll = poll
        self.cancelled = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"spark-monitor-{job_id[:8]}", daemon=True)

    def __enter__(self):
        self.spark.sparkContext.setJobGroup(self.job_id, f"nl-regex job {self.job_id}", interruptOnCancel=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        self._thread.join(timeout=5)
        # PySpark 3.5 exposes setJobGroup/cancelJobGroup but not clearJobGroup on the Python API
        self.spark.sparkContext._jsc.clearJobGroup()
        return False

    def _run(self) -> None:
        sc = self.spark.sparkContext
        tracker = sc.statusTracker()
        completed_stages: dict[int, int] = {}
        while not self._stop.wait(self.poll):
            try:
                if cancellation.is_cancel_requested(self.job_id):
                    logger.info("cancel requested for job %s: cancelling Spark job group", self.job_id)
                    self.cancelled = True
                    sc.cancelJobGroup(self.job_id)
                    return

                total_tasks = 0
                done_tasks = 0
                for stage_id in tracker.getActiveStageIds():
                    info = tracker.getStageInfo(stage_id)
                    if info is None:
                        continue
                    total_tasks += info.numTasks
                    done_tasks += info.numCompletedTasks
                    completed_stages[stage_id] = info.numTasks
                # count fully finished stages we saw earlier as done
                for stage_id, n in list(completed_stages.items()):
                    if stage_id not in tracker.getActiveStageIds():
                        total_tasks += n
                        done_tasks += n
                if total_tasks:
                    frac = min(1.0, done_tasks / total_tasks)
                    self.reporter.set_progress(int(self.start + frac * (self.end - self.start)))
            except Exception as exc:  # never let monitoring break the job
                logger.debug("spark monitor tick failed: %s", exc)
