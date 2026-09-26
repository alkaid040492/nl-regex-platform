"""
Load source files into Spark DataFrames.

* CSV is read straight from S3 through the s3a connector, so the read itself is
  distributed and split by `spark.sql.files.maxPartitionBytes`.
* Excel has no native Spark reader. Files are downloaded (by the caller), parsed with
  pandas/openpyxl, and converted with `spark.createDataFrame`. Excel is capped at ~1M rows
  per sheet by the format itself, so this path never sees "millions of rows".

Every column is loaded as a string: regex operations are string operations, and keeping
the source text verbatim avoids lossy numeric/date inference on columns we don't touch.
"""
from __future__ import annotations

import pandas as pd
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

ROW_ID_COLUMN = "_row_id"


def load_csv_from_s3(spark: SparkSession, bucket: str, key: str) -> DataFrame:
    return load_csv(spark, f"s3a://{bucket}/{key}")


def load_csv(spark: SparkSession, path: str) -> DataFrame:
    df = (
        spark.read.option("header", "true")
        .option("inferSchema", "false")
        .option("multiLine", "false")
        .option("escape", '"')
        .option("mode", "PERMISSIVE")
        .option("encoding", "UTF-8")
        .csv(path)
    )
    return _finalize(df)


def load_excel_from_local(spark: SparkSession, local_path: str, min_partitions: int) -> DataFrame:
    pdf = pd.read_excel(local_path, dtype=str).fillna("")
    pdf.columns = [str(c) for c in pdf.columns]
    if pdf.empty:
        df = spark.createDataFrame([], schema=", ".join(f"`{c}` string" for c in pdf.columns) or "`_empty` string")
    else:
        df = spark.createDataFrame(pdf)
    return _finalize(df.repartition(max(min_partitions, 1)))


def _finalize(df: DataFrame) -> DataFrame:
    """Clean column names, cast everything to string, add a stable row id for paging."""
    renamed = df.toDF(*[_clean_name(c, i) for i, c in enumerate(df.columns)])
    casted = renamed.select(*[F.col(f"`{c}`").cast("string").alias(c) for c in renamed.columns])
    return casted.withColumn(ROW_ID_COLUMN, F.monotonically_increasing_id())


def _clean_name(name: str, idx: int) -> str:
    name = (name or "").strip()
    if not name:
        name = f"column_{idx}"
    # Parquet forbids these characters in column names
    for ch in " ,;{}()\n\t=":
        name = name.replace(ch, "_")
    return name
