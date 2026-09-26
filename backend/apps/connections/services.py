"""
S3Service: thin, well-typed wrapper over boto3 for the operations the app needs.

All boto3 error mapping lives here so the API and Celery layers only deal with AppError
subclasses. Credentials are passed in explicitly; nothing is read from the environment
except an optional endpoint override for local MinIO.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import datetime

import boto3
import pandas as pd
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
)
from django.conf import settings

from .exceptions import AccessDenied, BucketNotFound, FileNotFound, InvalidCredentials, S3Unreachable, UnsupportedFile
from .store import S3Credentials

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".csv", ".xlsx", ".xls")
MAX_LISTED_FILES = 1000
PREVIEW_ROWS = 1000
PREVIEW_CSV_BYTES = 2 * 1024 * 1024
PREVIEW_EXCEL_MAX_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class S3File:
    key: str
    size: int
    last_modified: datetime
    kind: str  # "csv" | "excel"


@dataclass(frozen=True)
class SchemaPreview:
    columns: list[dict]  # [{name, dtype}]
    sample_rows: list[dict]
    sampled_rows: int


def file_kind(key: str) -> str:
    lower = key.lower()
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith((".xlsx", ".xls")):
        return "excel"
    raise UnsupportedFile(f"Unsupported file type for {key!r}. Only .csv, .xlsx and .xls are supported.")


def _translate(exc: Exception) -> Exception:
    """Map boto3/botocore exceptions to AppError subclasses with user-facing messages."""
    if isinstance(exc, (EndpointConnectionError, ConnectTimeoutError, ReadTimeoutError)):
        return S3Unreachable("Could not reach S3. Check the bucket region / endpoint and your network.")
    if isinstance(exc, NoCredentialsError):
        return InvalidCredentials("AWS credentials are missing.")
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        http = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"InvalidAccessKeyId", "SignatureDoesNotMatch", "AuthorizationHeaderMalformed", "InvalidToken"}:
            return InvalidCredentials("The AWS Access Key or Secret Key is invalid.")
        if code == "NoSuchBucket" or http == 404:
            return BucketNotFound("The bucket does not exist (or is in a different region).")
        if code in {"AccessDenied", "AllAccessDisabled"} or http == 403:
            return AccessDenied("These credentials are valid but do not have permission to access this bucket.")
        if code in {"PermanentRedirect", "IllegalLocationConstraintException"}:
            return BucketNotFound("The bucket exists in a different region. Please set the correct region.")
        return S3Unreachable(f"S3 returned an error ({code or http}).")
    return exc


class S3Service:
    def __init__(self, creds: S3Credentials):
        self._creds = creds
        endpoint = creds.endpoint_url or settings.S3_ENDPOINT_URL
        config = Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=30,
            s3={"addressing_style": "path"} if endpoint else {},
        )
        self._client = boto3.client(
            "s3",
            aws_access_key_id=creds.access_key,
            aws_secret_access_key=creds.secret_key,
            region_name=creds.region,
            endpoint_url=endpoint,
            config=config,
        )

    @property
    def bucket(self) -> str:
        return self._creds.bucket

    # -- connection --------------------------------------------------------
    def detect_region(self) -> str | None:
        """
        Ask S3 which region hosts the bucket, so users never have to know it.

        S3 returns the `x-amz-bucket-region` header on HeadBucket even when the request is
        signed for the wrong region (301) or lacks permission (403). A missing bucket or bad
        credentials come back without it; HEAD responses carry no error body, so in that
        case we return None and let `validate()` (ListObjectsV2, which does have a body)
        produce the precise error. Custom endpoints (dev mock) skip detection.
        """
        if self._creds.endpoint_url or settings.S3_ENDPOINT_URL:
            return None
        try:
            resp = self._client.head_bucket(Bucket=self.bucket)
            headers = resp.get("ResponseMetadata", {}).get("HTTPHeaders", {})
        except ClientError as exc:
            headers = exc.response.get("ResponseMetadata", {}).get("HTTPHeaders", {})
        except Exception as exc:  # noqa: BLE001
            raise _translate(exc) from None
        return headers.get("x-amz-bucket-region") or None

    def validate(self) -> None:
        """Raise a ConnectionError_ subclass if the credentials/bucket are unusable."""
        try:
            self._client.list_objects_v2(Bucket=self.bucket, MaxKeys=1)
        except Exception as exc:  # noqa: BLE001
            raise _translate(exc) from None


    # -- listing -----------------------------------------------------------
    def list_files(self, prefix: str = "") -> list[S3File]:
        files: list[S3File] = []
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("/") or not key.lower().endswith(SUPPORTED_EXTENSIONS):
                        continue
                    files.append(
                        S3File(key=key, size=obj["Size"], last_modified=obj["LastModified"], kind=file_kind(key))
                    )
                    if len(files) >= MAX_LISTED_FILES:
                        return files
        except Exception as exc:  # noqa: BLE001
            raise _translate(exc) from None
        files.sort(key=lambda f: f.last_modified, reverse=True)
        return files

    def head(self, key: str) -> S3File:
        try:
            meta = self._client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            translated = _translate(exc)
            if isinstance(translated, BucketNotFound):
                translated = FileNotFound(f"File {key!r} was not found in the bucket.")
            raise translated from None
        return S3File(key=key, size=meta["ContentLength"], last_modified=meta["LastModified"], kind=file_kind(key))

    # -- content -----------------------------------------------------------
    def download_to(self, key: str, path: str) -> None:
        try:
            self._client.download_file(self.bucket, key, path)
        except Exception as exc:  # noqa: BLE001
            raise _translate(exc) from None

    def preview_schema(self, key: str) -> SchemaPreview:
        """Infer columns from the head of the file without starting Spark."""
        kind = file_kind(key)
        try:
            if kind == "csv":
                obj = self._client.get_object(Bucket=self.bucket, Key=key, Range=f"bytes=0-{PREVIEW_CSV_BYTES - 1}")
                text = obj["Body"].read().decode("utf-8", errors="replace")
                # drop a possibly truncated last line
                if not text.endswith("\n") and "\n" in text:
                    text = text[: text.rfind("\n")]
                df = pd.read_csv(
                    io.StringIO(text), nrows=PREVIEW_ROWS, dtype=str, keep_default_na=False, on_bad_lines="skip"
                )
            else:
                info = self.head(key)
                if info.size > PREVIEW_EXCEL_MAX_BYTES:
                    raise UnsupportedFile("Excel files larger than 50 MB are not supported. Please convert to CSV.")
                obj = self._client.get_object(Bucket=self.bucket, Key=key)
                df = pd.read_excel(io.BytesIO(obj["Body"].read()), nrows=PREVIEW_ROWS, dtype=str).fillna("")
        except UnsupportedFile:
            raise
        except pd.errors.EmptyDataError:
            return SchemaPreview(columns=[], sample_rows=[], sampled_rows=0)
        except Exception as exc:  # noqa: BLE001
            raise _translate(exc) from None

        columns = [{"name": str(c), "dtype": _guess_dtype(df[c])} for c in df.columns]
        sample = df.head(5).astype(str).to_dict(orient="records")
        return SchemaPreview(columns=columns, sample_rows=sample, sampled_rows=int(len(df)))


def connect(creds: S3Credentials) -> S3Credentials:
    """Resolve the bucket's real region, verify access, and return credentials pinned to that region."""
    region = S3Service(creds).detect_region()
    if region and region != creds.region:
        creds = S3Credentials(**{**creds.__dict__, "region": region})
    S3Service(creds).validate()
    return creds


def _guess_dtype(series: pd.Series) -> str:
    """Cheap type hint for the UI (everything is read as string; Spark infers properly later)."""
    sample = series.dropna().astype(str).str.strip()
    sample = sample[sample != ""].head(200)
    if sample.empty:
        return "string"
    if pd.to_numeric(sample, errors="coerce").notna().all():
        return "number"
    return "string"
