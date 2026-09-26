"""
Regex transformations expressed as Spark column expressions.

Everything here is a pure DataFrame -> DataFrame function built from Catalyst-native
functions (`regexp_replace`, `regexp_extract`, `rlike`). No Python UDFs, no collect(), no
row iteration: Spark compiles these to JVM code and runs them per partition, so throughput
scales with cores/partitions rather than with Python interpreter speed.

A boolean `_matched` column is added so the caller can count affected rows and the UI can
highlight them, without a second pass over the data.
"""
from __future__ import annotations

from functools import reduce
from operator import or_

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

MATCHED_COLUMN = "_matched"


class TransformError(ValueError):
    """Raised for invalid transform arguments (unknown column, bad group, ...)."""


def escape_java_replacement(text: str) -> str:
    """Make a literal replacement string safe for Java's Matcher.appendReplacement ($ and \\)."""
    return text.replace("\\", "\\\\").replace("$", "\\$")


def _check_columns(df: DataFrame, columns: list[str]) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise TransformError(f"Column(s) not found in file: {', '.join(missing)}")
    if not columns:
        raise TransformError("At least one target column is required.")


def _any_match(columns: list[str], pattern: str) -> Column:
    return reduce(or_, [F.coalesce(F.col(f"`{c}`").rlike(pattern), F.lit(False)) for c in columns])


def replace(df: DataFrame, columns: list[str], pattern: str, replacement: str) -> DataFrame:
    """Replace every match of `pattern` in each target column with the literal `replacement`."""
    _check_columns(df, columns)
    safe_replacement = escape_java_replacement(replacement)
    out = df.withColumn(MATCHED_COLUMN, _any_match(columns, pattern))
    for c in columns:
        out = out.withColumn(c, F.regexp_replace(F.col(f"`{c}`"), pattern, safe_replacement))
    return out


def extract(df: DataFrame, columns: list[str], pattern: str, new_column: str, group: int = 0) -> DataFrame:
    """
    Extract the match (or capture `group`) of `pattern` into a new column.
    With one source column the new column is `new_column`; with several it is `<col>_<new_column>`.
    """
    _check_columns(df, columns)
    if not new_column:
        raise TransformError("A name for the new column is required.")
    out = df.withColumn(MATCHED_COLUMN, _any_match(columns, pattern))
    for c in columns:
        target = new_column if len(columns) == 1 else f"{c}_{new_column}"
        if target in df.columns:
            raise TransformError(f"Column {target!r} already exists.")
        out = out.withColumn(target, F.regexp_extract(F.col(f"`{c}`"), pattern, group))
    return out


def normalize(df: DataFrame, columns: list[str], pattern: str, template: str) -> DataFrame:
    """
    Rewrite matches using a Java replacement template with back-references ($1, $2 ...),
    e.g. pattern (\\d{4})/(\\d{2})/(\\d{2}) with template $3-$2-$1 turns 2024/01/05 into 05-01-2024.
    The template is applied verbatim (not escaped) — it must be validated upstream.
    """
    _check_columns(df, columns)
    out = df.withColumn(MATCHED_COLUMN, _any_match(columns, pattern))
    for c in columns:
        out = out.withColumn(c, F.regexp_replace(F.col(f"`{c}`"), pattern, template))
    return out


def apply_transform(
    df: DataFrame,
    *,
    transform_type: str,
    columns: list[str],
    pattern: str,
    replacement: str = "",
    replacement_template: str = "",
    new_column: str = "",
    group: int = 0,
) -> DataFrame:
    """Dispatch by transform type. Keeps the task layer free of engine specifics."""
    if transform_type == "REPLACE":
        return replace(df, columns, pattern, replacement)
    if transform_type == "EXTRACT":
        return extract(df, columns, pattern, new_column, group)
    if transform_type == "NORMALIZE":
        return normalize(df, columns, pattern, replacement_template)
    raise TransformError(f"Unknown transform type {transform_type!r}")
