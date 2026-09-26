"""Persist a transformed DataFrame as Parquet on the shared results volume."""
from __future__ import annotations

import os
import shutil

from pyspark.sql import DataFrame


def result_dir(results_root: str, job_id: str) -> str:
    return os.path.join(results_root, str(job_id))


def write_parquet(df: DataFrame, path: str) -> str:
    """
    Write `df` to `path` (overwriting). Snappy-compressed Parquet keeps the on-disk footprint
    small and lets DuckDB page through it with predicate/projection pushdown.
    """
    df.write.mode("overwrite").option("compression", "snappy").parquet(path)
    return path


def delete_result(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)
