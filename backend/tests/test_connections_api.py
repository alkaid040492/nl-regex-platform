from unittest import mock

import pytest
from botocore.exceptions import ClientError
from rest_framework.test import APIClient

from apps.connections import store
from apps.connections.exceptions import InvalidCredentials
from apps.connections.services import S3Service, _translate
from apps.connections.store import S3Credentials
from apps.core.logging import mask

pytestmark = pytest.mark.django_db

CREDS = {"access_key": "testing", "secret_key": "testing", "bucket": "demo"}


@pytest.fixture
def api():
    return APIClient()


def test_store_roundtrip_is_encrypted_and_expires():
    creds = S3Credentials(access_key="AKIAABCDEFGHIJKLMNOP", secret_key="s3cr3t", bucket="b", region="us-east-1")
    cid, expires = store.save(creds)
    raw = store.get_redis().get("conn:" + cid)
    assert b"s3cr3t" not in raw and b"AKIAABCDEFGHIJKLMNOP" not in raw
    assert store.get_redis().ttl("conn:" + cid) > 0
    loaded = store.load(cid)
    assert loaded == creds
    assert "s3cr3t" not in repr(loaded) and loaded.access_key_hint == "****MNOP"
    store.delete(cid)
    with pytest.raises(Exception) as exc:
        store.load(cid)
    assert exc.value.code == "CONNECTION_EXPIRED"


def test_create_connection_and_list_files(api, s3):
    res = api.post("/api/connections/", CREDS, format="json")
    assert res.status_code == 201, res.content
    body = res.json()
    assert "secret_key" not in body and body["access_key_hint"] == "****ting"
    cid = body["connection_id"]

    files = api.get(f"/api/connections/{cid}/files/").json()["files"]
    keys = sorted(f["key"] for f in files)
    assert keys == ["folder/sample.xlsx", "sample.csv"]  # notes.txt filtered out
    assert {f["kind"] for f in files} == {"csv", "excel"}

    schema = api.get(f"/api/connections/{cid}/files/schema/", {"key": "sample.csv"}).json()
    assert [c["name"] for c in schema["columns"]] == ["ID", "Name", "Email", "Phone", "JoinDate"]
    assert schema["columns"][0]["dtype"] == "number"
    assert schema["sampled_rows"] == 4

    schema_x = api.get(f"/api/connections/{cid}/files/schema/", {"key": "folder/sample.xlsx"}).json()
    assert [c["name"] for c in schema_x["columns"]] == ["ID", "Name", "Email", "Phone", "JoinDate"]

    assert api.delete(f"/api/connections/{cid}/").status_code == 204
    assert api.get(f"/api/connections/{cid}/files/").status_code == 404


def test_invalid_bucket_name_is_validation_error(api):
    res = api.post("/api/connections/", {**CREDS, "bucket": "Bad_Bucket!"}, format="json")
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


def test_invalid_credentials_surface_as_typed_error(api):
    with mock.patch.object(S3Service, "validate", side_effect=InvalidCredentials("bad key")):
        res = api.post("/api/connections/", CREDS, format="json")
    assert res.status_code == 400
    assert res.json() == {"code": "INVALID_CREDENTIALS", "message": "bad key"}


def test_unsupported_file_type(api, s3):
    cid = api.post("/api/connections/", CREDS, format="json").json()["connection_id"]
    res = api.get(f"/api/connections/{cid}/files/schema/", {"key": "notes.txt"})
    assert res.status_code == 400 and res.json()["code"] == "UNSUPPORTED_FILE"


@pytest.mark.parametrize(
    "code,http,expected",
    [
        ("InvalidAccessKeyId", 403, "INVALID_CREDENTIALS"),
        ("SignatureDoesNotMatch", 403, "INVALID_CREDENTIALS"),
        ("AccessDenied", 403, "ACCESS_DENIED"),
        ("NoSuchBucket", 404, "BUCKET_NOT_FOUND"),
        ("PermanentRedirect", 301, "BUCKET_NOT_FOUND"),
        ("SlowDown", 503, "NETWORK_ERROR"),
    ],
)
def test_boto_error_translation(code, http, expected):
    exc = ClientError({"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": http}}, "ListObjectsV2")
    assert _translate(exc).code == expected


def test_log_masking():
    line = "creds AKIAIOSFODNN7EXAMPLE secret_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY ok"
    masked = mask(line)
    assert "AKIAIOSFODNN7EXAMPLE" not in masked
    assert "wJalrXUtnFEMI" not in masked
