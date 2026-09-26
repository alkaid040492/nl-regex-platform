"""
SparkSession factory and per-bucket S3 credential wiring.

This module is framework-free (no Django import) so the engine can be tested and reused
outside the web/worker processes. Configuration is passed in explicitly via SparkConfig.

Design notes
------------
* One SparkSession per worker process, created lazily and reused across jobs. Creating a
  JVM is expensive (seconds); Celery runs with --pool=solo so there is exactly one.
* Credentials are scoped per bucket with the `fs.s3a.bucket.<name>.*` overrides, so two
  jobs touching different buckets never share keys, and are removed after each job.
* `fs.s3a.impl.disable.cache=true` prevents Hadoop from caching an S3A FileSystem instance
  (which would pin the first credentials used for a bucket name).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from pyspark.sql import SparkSession

S3A_IMPL = "org.apache.hadoop.fs.s3a.S3AFileSystem"
SIMPLE_CREDENTIALS_PROVIDER = "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider"


@dataclass(frozen=True)
class SparkConfig:
    master: str = "local[*]"
    driver_memory: str = "2g"
    shuffle_partitions: int = 16
    app_name: str = "nl-regex-engine"
    max_partition_bytes: str = "32m"  # smaller than the 128m default → more parallelism on mid-size CSVs
    ui_enabled: bool = False


_session: SparkSession | None = None


def get_spark(config: SparkConfig) -> SparkSession:
    """Return the process-wide SparkSession, creating it on first use."""
    global _session
    if _session is not None:
        return _session

    # driver memory must be known before the JVM starts; PySpark reads it from submit args
    os.environ.setdefault("PYSPARK_SUBMIT_ARGS", f"--driver-memory {config.driver_memory} pyspark-shell")

    builder = (
        SparkSession.builder.appName(config.app_name)
        .master(config.master)
        .config("spark.driver.memory", config.driver_memory)
        .config("spark.sql.shuffle.partitions", str(config.shuffle_partitions))
        .config("spark.sql.files.maxPartitionBytes", config.max_partition_bytes)
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.enabled", str(config.ui_enabled).lower())
        .config("spark.ui.showConsoleProgress", "false")
        .config("spark.hadoop.fs.s3a.impl", S3A_IMPL)
        .config("spark.hadoop.fs.s3a.aws.credentials.provider", SIMPLE_CREDENTIALS_PROVIDER)
        .config("spark.hadoop.fs.s3a.impl.disable.cache", "true")
        .config("spark.hadoop.fs.s3a.connection.maximum", "64")
        .config("spark.hadoop.fs.s3a.attempts.maximum", "3")
        .config("spark.hadoop.fs.s3a.connection.establish.timeout", "5000")
        .config("spark.hadoop.fs.s3a.connection.timeout", "60000")
        .config("spark.hadoop.fs.s3a.fast.upload", "true")
    )
    _session = builder.getOrCreate()
    _session.sparkContext.setLogLevel("WARN")
    return _session


def stop_spark() -> None:
    global _session
    if _session is not None:
        _session.stop()
        _session = None


# --- per-bucket credentials --------------------------------------------------

def _bucket_keys(bucket: str) -> dict[str, str | None]:
    p = f"fs.s3a.bucket.{bucket}."
    return {
        p + "access.key": None,
        p + "secret.key": None,
        p + "endpoint": None,
        p + "endpoint.region": None,
        p + "path.style.access": None,
        p + "connection.ssl.enabled": None,
    }


def configure_bucket_credentials(
    spark: SparkSession,
    *,
    bucket: str,
    access_key: str,
    secret_key: str,
    region: str | None = None,
    endpoint_url: str | None = None,
) -> None:
    """Attach credentials to one bucket only. Call clear_bucket_credentials() when done."""
    hconf = spark.sparkContext._jsc.hadoopConfiguration()
    p = f"fs.s3a.bucket.{bucket}."
    hconf.set(p + "access.key", access_key)
    hconf.set(p + "secret.key", secret_key)
    if endpoint_url:
        # MinIO / custom endpoint
        hconf.set(p + "endpoint", endpoint_url)
        hconf.set(p + "path.style.access", "true")
        hconf.set(p + "connection.ssl.enabled", "true" if endpoint_url.startswith("https://") else "false")
    elif region:
        hconf.set(p + "endpoint.region", region)
        hconf.set(p + "endpoint", f"s3.{region}.amazonaws.com")


def clear_bucket_credentials(spark: SparkSession, bucket: str) -> None:
    hconf = spark.sparkContext._jsc.hadoopConfiguration()
    for key in _bucket_keys(bucket):
        hconf.unset(key)
