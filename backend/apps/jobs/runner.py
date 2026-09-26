"""
JobRunner: orchestrates one job through its stages. Lives in the task layer; it knows about
Django models and settings, and calls into the framework-free engine and llm packages.

Stages and progress ranges
    LOAD       0-10   read the source into a DataFrame (s3a for CSV, download+pandas for Excel)
    LLM       10-25   natural language -> RegexSpec (Redis cache first)
    VALIDATE  25-30   python/regex-module checks + JVM compile check
    TRANSFORM 30-90   Spark action (write Parquet) — progress from Spark's status tracker
    WRITE     90-100  stats via DuckDB, finalize the Job row

Failure handling
    * AppError subclasses carry a code the UI can show (INVALID_REGEX, CONNECTION_EXPIRED, ...)
    * Transient errors (LLMTransientError, S3Unreachable) are retried by the task with backoff
    * Cancellation is cooperative (flag checked between stages + Spark job-group cancel)
    * SoftTimeLimitExceeded is translated to FAILED/TIMEOUT
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.utils import timezone
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from apps.connections import store
from apps.connections.exceptions import S3Unreachable
from apps.connections.services import S3Service, file_kind
from apps.core.exceptions import AppError
from apps.engine import loaders, session, transforms, writer
from apps.engine.java_regex import java_compile_error
from apps.engine.reader import ResultReader
from apps.llm import cache as llm_cache
from apps.llm.client import LLMTransientError, RegexGenerator, build_generator
from apps.llm.schemas import RegexSpec
from apps.llm.validation import InvalidRegex, validate_pattern, validate_replacement_template

from . import cancellation
from .models import Job
from .progress import ProgressReporter, SparkStageMonitor

logger = logging.getLogger(__name__)

RETRYABLE = (LLMTransientError, S3Unreachable)
SAMPLE_ROWS = 8


class RetryableFailure(Exception):
    """Wraps a transient error so the task layer can decide to retry."""

    def __init__(self, original: AppError):
        super().__init__(str(original))
        self.original = original


def spark_config() -> session.SparkConfig:
    return session.SparkConfig(
        master=settings.SPARK_MASTER,
        driver_memory=settings.SPARK_DRIVER_MEMORY,
        shuffle_partitions=settings.SPARK_SHUFFLE_PARTITIONS,
    )


class JobRunner:
    def __init__(self, job: Job, llm: RegexGenerator | None = None, spark: SparkSession | None = None):
        self.job = job
        self.llm = llm or build_generator()
        self._spark = spark
        self.reporter = ProgressReporter(job)
        self._workdir: str | None = None

    # ------------------------------------------------------------------ public
    def run(self) -> Job:
        job = self.job
        if job.status == Job.Status.CANCELLED or cancellation.is_cancel_requested(str(job.id)):
            return self._finish_cancelled()
        Job.objects.filter(pk=job.pk).update(status=Job.Status.RUNNING, started_at=timezone.now(), error_code="", error_message="")
        try:
            df, creds = self._load()
            spec = self._generate_regex(df)
            pattern, template = self._validate(spec, df)
            self._transform_and_write(df, pattern, template, spec)
            return self._finish_success()
        except cancellation.JobCancelled:
            return self._finish_cancelled()
        except SoftTimeLimitExceeded:
            self._cancel_spark_quietly()
            return self._finish_failed("TIMEOUT", "The job exceeded the maximum allowed run time.")
        except RETRYABLE as exc:
            raise RetryableFailure(exc) from exc
        except AppError as exc:
            return self._finish_failed(exc.code, exc.message)
        except transforms.TransformError as exc:
            return self._finish_failed("INVALID_COLUMNS", str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("job %s crashed", job.id)
            return self._finish_failed("INTERNAL_ERROR", _short_error(exc))
        finally:
            self._cleanup()

    # ------------------------------------------------------------------ stages
    def _load(self) -> tuple[DataFrame, store.S3Credentials]:
        job = self.job
        self.reporter.set_stage(Job.Stage.LOAD, 2)
        creds = store.load(str(job.connection_id))  # CONNECTION_EXPIRED if gone
        spark = self.spark
        kind = file_kind(job.file_key)
        info = S3Service(creds).head(job.file_key)  # typed error if the object is gone / unreadable
        logger.info("job %s loading %s (%s, %.1f MB)", job.id, job.file_key, kind, info.size / 1024 / 1024)

        if kind == "csv":
            session.configure_bucket_credentials(
                spark,
                bucket=creds.bucket,
                access_key=creds.access_key,
                secret_key=creds.secret_key,
                region=creds.region,
                endpoint_url=creds.endpoint_url,
            )
            self._bucket_configured = creds.bucket
            df = loaders.load_csv_from_s3(spark, creds.bucket, job.file_key)
        else:
            self._workdir = tempfile.mkdtemp(prefix="nlregex-")
            local = os.path.join(self._workdir, os.path.basename(job.file_key))
            S3Service(creds).download_to(job.file_key, local)
            df = loaders.load_excel_from_local(spark, local, spark.sparkContext.defaultParallelism)

        missing = [c for c in job.columns if c not in df.columns]
        if missing:
            raise transforms.TransformError(f"Column(s) not found in file: {', '.join(missing)}")

        self.reporter.set_stage(Job.Stage.LOAD, 10)
        self._check_cancel()
        return df, creds

    def _generate_regex(self, df: DataFrame) -> RegexSpec:
        job = self.job
        self.reporter.set_stage(Job.Stage.LLM, 12)
        spec = llm_cache.get(job.transform_type, job.prompt)
        if spec is None:
            samples = self._sample_values(df)
            spec = self.llm.generate(job.transform_type, job.prompt, job.columns, samples)
            llm_cache.put(job.transform_type, job.prompt, spec)
        Job.objects.filter(pk=job.pk).update(
            regex_pattern=spec.pattern,
            replacement_template=spec.replacement_template,
            llm_explanation=spec.explanation,
            llm_cache_hit=spec.cached,
        )
        self.reporter.set_stage(Job.Stage.LLM, 25)
        self._check_cancel()
        return spec

    def _validate(self, spec: RegexSpec, df: DataFrame) -> tuple[str, str]:
        job = self.job
        self.reporter.set_stage(Job.Stage.VALIDATE, 26)
        samples = [v for vals in self._sample_values(df).values() for v in vals]
        min_groups = 1 if job.transform_type == Job.TransformType.NORMALIZE else 0
        if job.transform_type == Job.TransformType.EXTRACT:
            min_groups = max(min_groups, spec.group)

        try:
            validated = validate_pattern(spec.pattern, samples, min_groups=min_groups)
        except AppError:
            # a cached-but-bad pattern must not poison future runs
            llm_cache.invalidate(job.transform_type, job.prompt)
            raise

        java_error = java_compile_error(self.spark, validated.pattern)
        if java_error:
            llm_cache.invalidate(job.transform_type, job.prompt)
            raise InvalidRegex(f"Spark's regex engine rejected the pattern: {java_error}")

        template = ""
        if job.transform_type == Job.TransformType.NORMALIZE:
            template = validate_replacement_template(spec.replacement_template, validated.groups)

        Job.objects.filter(pk=job.pk).update(regex_pattern=validated.pattern, replacement_template=template)
        self.reporter.set_stage(Job.Stage.VALIDATE, 30)
        self._check_cancel()
        return validated.pattern, template

    def _transform_and_write(self, df: DataFrame, pattern: str, template: str, spec: RegexSpec) -> None:
        job = self.job
        self.reporter.set_stage(Job.Stage.TRANSFORM, 31)
        out = transforms.apply_transform(
            df,
            transform_type=job.transform_type,
            columns=list(job.columns),
            pattern=pattern,
            replacement=job.replacement,
            replacement_template=template,
            new_column=job.new_column_name,
            group=spec.group,
        )
        path = writer.result_dir(settings.RESULTS_DIR, str(job.id))
        with SparkStageMonitor(self.spark, self.reporter, str(job.id), start=31, end=90) as monitor:
            try:
                writer.write_parquet(out, path)
            except Exception:
                if monitor.cancelled or cancellation.is_cancel_requested(str(job.id)):
                    writer.delete_result(path)
                    raise cancellation.JobCancelled()
                raise
        self._result_path = path
        self.reporter.set_stage(Job.Stage.WRITE, 92)

    # ---------------------------------------------------------------- finishing
    def _finish_success(self) -> Job:
        job = self.job
        stats = ResultReader(self._result_path).stats()
        Job.objects.filter(pk=job.pk).update(
            status=Job.Status.SUCCESS,
            stage=Job.Stage.DONE,
            progress=100,
            row_count=stats.total_rows,
            matched_rows=stats.matched_rows,
            result_columns=stats.columns,
            result_path=self._result_path,
            finished_at=timezone.now(),
        )
        job.refresh_from_db()
        logger.info("job %s SUCCESS rows=%s matched=%s", job.id, stats.total_rows, stats.matched_rows)
        return job

    def _finish_failed(self, code: str, message: str) -> Job:
        job = self.job
        Job.objects.filter(pk=job.pk).update(
            status=Job.Status.FAILED, stage=Job.Stage.DONE, error_code=code, error_message=message[:2000],
            finished_at=timezone.now(),
        )
        job.refresh_from_db()
        logger.warning("job %s FAILED %s: %s", job.id, code, message)
        return job

    def _finish_cancelled(self) -> Job:
        job = self.job
        Job.objects.filter(pk=job.pk).update(status=Job.Status.CANCELLED, stage=Job.Stage.DONE, finished_at=timezone.now())
        cancellation.clear(str(job.id))
        job.refresh_from_db()
        logger.info("job %s CANCELLED", job.id)
        return job

    # ------------------------------------------------------------------ helpers
    @property
    def spark(self) -> SparkSession:
        if self._spark is None:
            self._spark = session.get_spark(spark_config())
        return self._spark

    _bucket_configured: str | None = None
    _result_path: str = ""
    _samples_cache: dict[str, list[str]] | None = None

    def _sample_values(self, df: DataFrame) -> dict[str, list[str]]:
        if self._samples_cache is None:
            cols = [F.col(f"`{c}`") for c in self.job.columns]
            rows = df.select(*cols).where(" OR ".join(f"`{c}` IS NOT NULL AND `{c}` != ''" for c in self.job.columns)).limit(SAMPLE_ROWS).collect()
            self._samples_cache = {
                c: [str(r[i]) for r in rows if r[i] not in (None, "")] for i, c in enumerate(self.job.columns)
            }
        return self._samples_cache

    def _check_cancel(self) -> None:
        if cancellation.is_cancel_requested(str(self.job.id)):
            raise cancellation.JobCancelled()

    def _cancel_spark_quietly(self) -> None:
        try:
            if self._spark is not None:
                self._spark.sparkContext.cancelJobGroup(str(self.job.id))
        except Exception:
            pass

    def _cleanup(self) -> None:
        if self._bucket_configured and self._spark is not None:
            try:
                session.clear_bucket_credentials(self._spark, self._bucket_configured)
            except Exception:
                pass
        if self._workdir:
            shutil.rmtree(self._workdir, ignore_errors=True)


def _short_error(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    first = text.strip().splitlines()[0] if text.strip() else exc.__class__.__name__
    return first[:500]
