"""
Shared fixtures.

* `spark`     session-scoped local[2] SparkSession (slow to start, so shared)
* `s3`        moto-mocked S3 with a bucket containing sample CSV/XLSX files
* `redis`     the real Redis (db 15 in docker-compose), flushed between tests
* `fake_llm`  deterministic RegexGenerator
"""
from __future__ import annotations

import io
import os

import boto3
import pandas as pd
import pytest
from moto import mock_aws

from apps.core.redis import get_redis
from apps.engine.session import SparkConfig, get_spark
from apps.llm.client import FakeLLM
from apps.llm.schemas import RegexSpec

SAMPLE_ROWS = [
    {"ID": "1", "Name": "John Doe", "Email": "john.doe@example.com", "Phone": "+1-555-123-4567", "JoinDate": "2024/01/05"},
    {"ID": "2", "Name": "Jane Smith", "Email": "jane_smith@domain.com", "Phone": "(555) 987-6543", "JoinDate": "2023/11/30"},
    {"ID": "3", "Name": "Alice Brown", "Email": "alice.brown@website.org", "Phone": "555.246.8100", "JoinDate": "2024/03/17"},
    {"ID": "4", "Name": "No Email", "Email": "", "Phone": "", "JoinDate": "2022/07/01"},
]
EMAIL_PATTERN = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b"


@pytest.fixture(scope="session")
def spark():
    os.environ.setdefault("PYSPARK_SUBMIT_ARGS", "--driver-memory 1g pyspark-shell")
    s = get_spark(SparkConfig(master="local[2]", driver_memory="1g", shuffle_partitions=2, app_name="tests"))
    yield s


@pytest.fixture
def sample_pdf() -> pd.DataFrame:
    return pd.DataFrame(SAMPLE_ROWS)


@pytest.fixture
def sample_csv_path(tmp_path, sample_pdf) -> str:
    p = tmp_path / "sample.csv"
    sample_pdf.to_csv(p, index=False)
    return str(p)


@pytest.fixture
def sample_df(spark, sample_csv_path):
    from apps.engine.loaders import load_csv

    return load_csv(spark, sample_csv_path)


@pytest.fixture(autouse=True)
def _flush_redis():
    r = get_redis()
    r.flushdb()
    yield
    r.flushdb()


@pytest.fixture
def s3(sample_pdf):
    """moto S3 with bucket `demo` holding sample.csv and sample.xlsx."""
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")
        client.create_bucket(Bucket="demo")
        client.put_object(Bucket="demo", Key="sample.csv", Body=sample_pdf.to_csv(index=False).encode())
        buf = io.BytesIO()
        sample_pdf.to_excel(buf, index=False)
        client.put_object(Bucket="demo", Key="folder/sample.xlsx", Body=buf.getvalue())
        client.put_object(Bucket="demo", Key="notes.txt", Body=b"ignore me")
        yield client


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM(RegexSpec(pattern=EMAIL_PATTERN, explanation="emails"))
