"""
Seed a local S3-compatible bucket (MinIO) with sample files for development.

    python manage.py seed_s3 --endpoint http://minio:9000 --bucket demo --source /sample

Idempotent: creates the bucket if missing and uploads every file in --source.
"""
from __future__ import annotations

import os
import time

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create a bucket on a local S3 endpoint and upload sample files."

    def add_arguments(self, parser):
        parser.add_argument("--endpoint", default=os.environ.get("S3_ENDPOINT_URL", "http://minio:9000"))
        parser.add_argument("--bucket", default="demo")
        parser.add_argument("--source", default="/sample")
        parser.add_argument("--access-key", default=os.environ.get("MINIO_ROOT_USER", "minioadmin"))
        parser.add_argument("--secret-key", default=os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin"))
        parser.add_argument("--wait", type=int, default=60, help="seconds to wait for the endpoint")

    def handle(self, *args, **opts):
        client = boto3.client(
            "s3",
            endpoint_url=opts["endpoint"],
            aws_access_key_id=opts["access_key"],
            aws_secret_access_key=opts["secret_key"],
            region_name="us-east-1",
        )
        # Java-based S3 mocks (S3Mock, some MinIO builds) close the connection on
        # botocore's `Expect: 100-continue` PUTs. Real S3 never needs this hook.
        def _strip_expect(request, **_kw):
            request.headers.pop("Expect", None)
            return None  # a non-None return would be treated as the HTTP response

        client.meta.events.register_first("before-send.s3.*", _strip_expect)
        deadline = time.time() + opts["wait"]
        while True:
            try:
                client.list_buckets()
                break
            except (EndpointConnectionError, ClientError) as exc:
                if time.time() > deadline:
                    raise SystemExit(f"S3 endpoint not reachable: {exc}")
                time.sleep(2)

        bucket = opts["bucket"]
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError:
            client.create_bucket(Bucket=bucket)
            self.stdout.write(f"created bucket {bucket}")

        source = opts["source"]
        count = 0
        for root, _dirs, files in os.walk(source):
            for name in files:
                path = os.path.join(root, name)
                key = os.path.relpath(path, source).replace(os.sep, "/")
                with open(path, "rb") as fh:  # one PUT per file; S3Mock is unreliable with multipart parts
                    client.put_object(Bucket=bucket, Key=key, Body=fh)
                count += 1
        self.stdout.write(self.style.SUCCESS(f"uploaded {count} file(s) to {bucket} at {opts['endpoint']}"))
