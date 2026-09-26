"""Compile a pattern with the JVM's java.util.regex via py4j — the engine that will run it."""
from __future__ import annotations

from pyspark.sql import SparkSession


def java_compile_error(spark: SparkSession, pattern: str) -> str | None:
    """Return None if Java accepts the pattern, otherwise the PatternSyntaxException message."""
    try:
        spark._jvm.java.util.regex.Pattern.compile(pattern)  # type: ignore[attr-defined]
        return None
    except Exception as exc:  # py4j wraps PatternSyntaxException
        message = str(exc)
        marker = "java.util.regex.PatternSyntaxException:"
        if marker in message:
            message = message.split(marker, 1)[1].strip().splitlines()[0]
        return message[:300]
