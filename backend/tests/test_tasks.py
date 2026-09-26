"""
End-to-end task tests: API submit → Celery (eager) → JobRunner → Spark → Parquet → paged result.
Uses the Excel path (boto3 download) so moto can serve the file; the CSV/s3a path is exercised
against MinIO/S3 in integration runs.
"""
from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.connections import store
from apps.connections.store import S3Credentials
from apps.jobs import cancellation
from apps.jobs.models import Job
from apps.jobs.runner import JobRunner
from apps.llm import cache as llm_cache
from apps.llm.client import FakeLLM
from apps.llm.schemas import RegexSpec

from .conftest import EMAIL_PATTERN

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.spark]


@pytest.fixture
def connection_id(s3):
    cid, _ = store.save(S3Credentials(access_key="testing", secret_key="testing", bucket="demo", region="us-east-1"))
    return cid


@pytest.fixture
def results_dir(tmp_path, settings):
    settings.RESULTS_DIR = str(tmp_path / "results")
    return settings.RESULTS_DIR


def _make_job(connection_id, **overrides) -> Job:
    params = dict(
        connection_id=connection_id,
        bucket="demo",
        file_key="folder/sample.xlsx",
        transform_type="REPLACE",
        prompt="find email addresses",
        replacement="REDACTED",
        columns=["Email"],
    )
    params.update(overrides)
    return Job.objects.create(**params)


def test_replace_job_end_to_end(spark, connection_id, results_dir, fake_llm):
    job = _make_job(connection_id)
    job = JobRunner(job, llm=fake_llm, spark=spark).run()

    assert job.status == Job.Status.SUCCESS, (job.error_code, job.error_message)
    assert job.progress == 100 and job.stage == Job.Stage.DONE
    assert job.row_count == 4 and job.matched_rows == 3
    assert job.regex_pattern == EMAIL_PATTERN
    assert job.llm_cache_hit is False
    assert job.result_columns == ["ID", "Name", "Email", "Phone", "JoinDate"]

    res = APIClient().get(f"/api/jobs/{job.id}/result/", {"page": 1, "page_size": 2})
    assert res.status_code == 200
    body = res.json()
    assert body["total_rows"] == 4 and body["total_pages"] == 2
    assert [r["Email"] for r in body["rows"]] == ["REDACTED", "REDACTED"]


def test_second_identical_prompt_hits_cache(spark, connection_id, results_dir, fake_llm):
    JobRunner(_make_job(connection_id), llm=fake_llm, spark=spark).run()
    job2 = JobRunner(_make_job(connection_id, prompt="  Find Email   addresses "), llm=fake_llm, spark=spark).run()
    assert job2.status == Job.Status.SUCCESS
    assert job2.llm_cache_hit is True
    assert len(fake_llm.calls) == 1


def test_extract_and_normalize(spark, connection_id, results_dir):
    llm = FakeLLM(RegexSpec(pattern=r"@([A-Za-z0-9.-]+)", group=1))
    job = JobRunner(_make_job(connection_id, transform_type="EXTRACT", new_column_name="domain", prompt="domain"), llm=llm, spark=spark).run()
    assert job.status == Job.Status.SUCCESS
    assert "domain" in job.result_columns

    llm = FakeLLM(RegexSpec(pattern=r"(\d{4})/(\d{2})/(\d{2})", replacement_template="$3-$2-$1"))
    job = JobRunner(_make_job(connection_id, transform_type="NORMALIZE", columns=["JoinDate"], prompt="dd-mm-yyyy"), llm=llm, spark=spark).run()
    assert job.status == Job.Status.SUCCESS
    page = APIClient().get(f"/api/jobs/{job.id}/result/").json()
    assert page["rows"][0]["JoinDate"] == "05-01-2024"


def test_unsafe_regex_fails_job_and_evicts_cache(spark, connection_id, results_dir):
    llm = FakeLLM(RegexSpec(pattern=r"(a+)+$"))
    job = JobRunner(_make_job(connection_id, prompt="evil"), llm=llm, spark=spark).run()
    assert job.status == Job.Status.FAILED
    assert job.error_code == "UNSAFE_REGEX"
    assert llm_cache.get("REPLACE", "evil") is None


def test_java_rejects_pattern_python_accepts(spark, connection_id, results_dir):
    # (?a) is a Python-only inline flag: Python compiles it, java.util.regex throws PatternSyntaxException
    llm = FakeLLM(RegexSpec(pattern=r"(?a)\w+"))
    job = JobRunner(_make_job(connection_id, prompt="badref"), llm=llm, spark=spark).run()
    assert job.status == Job.Status.FAILED and job.error_code == "INVALID_REGEX"


def test_missing_column_fails_cleanly(spark, connection_id, results_dir, fake_llm):
    job = JobRunner(_make_job(connection_id, columns=["Nope"]), llm=fake_llm, spark=spark).run()
    assert job.status == Job.Status.FAILED and job.error_code == "INVALID_COLUMNS"


def test_expired_connection_fails(spark, results_dir, fake_llm):
    job = _make_job("00000000-0000-0000-0000-000000000000")
    job = JobRunner(job, llm=fake_llm, spark=spark).run()
    assert job.status == Job.Status.FAILED and job.error_code == "CONNECTION_EXPIRED"


def test_cancel_before_start(spark, connection_id, results_dir, fake_llm):
    job = _make_job(connection_id)
    cancellation.request_cancel(str(job.id))
    job = JobRunner(job, llm=fake_llm, spark=spark).run()
    assert job.status == Job.Status.CANCELLED
    assert not cancellation.is_cancel_requested(str(job.id))


def test_submit_via_api_runs_eagerly(spark, connection_id, results_dir, fake_llm):
    api = APIClient()
    with mock.patch("apps.jobs.runner.build_generator", return_value=fake_llm), mock.patch(
        "apps.engine.session.get_spark", return_value=spark
    ):
        res = api.post(
            "/api/jobs/",
            {
                "connection_id": connection_id,
                "file_key": "folder/sample.xlsx",
                "transform_type": "REPLACE",
                "prompt": "find emails",
                "replacement": "X",
                "columns": ["Email"],
            },
            format="json",
        )
    assert res.status_code == 202, res.content
    job = Job.objects.get(pk=res.json()["job_id"])
    assert job.status == Job.Status.SUCCESS
    detail = api.get(f"/api/jobs/{job.id}/").json()
    assert detail["status"] == "SUCCESS" and detail["matched_rows"] == 3
    assert api.post(f"/api/jobs/{job.id}/cancel/").status_code == 409


def test_api_validation(connection_id):
    api = APIClient()
    bad = api.post("/api/jobs/", {"connection_id": connection_id, "file_key": "a.csv", "transform_type": "EXTRACT",
                                  "prompt": "x y z", "columns": ["Email"]}, format="json")
    assert bad.status_code == 400 and "new_column_name" in bad.json()["details"]
    gone = api.post("/api/jobs/", {"connection_id": "00000000-0000-0000-0000-000000000000", "file_key": "a.csv",
                                   "transform_type": "REPLACE", "prompt": "x y z", "columns": ["Email"]}, format="json")
    assert gone.status_code == 404 and gone.json()["code"] == "CONNECTION_EXPIRED"
