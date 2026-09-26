"""API layer for S3 connections. Thin: validate input, call service, shape response."""
from __future__ import annotations

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import store
from .serializers import ConnectionCreateSerializer, FileListQuerySerializer, SchemaQuerySerializer
from .services import S3Service
from .store import S3Credentials

logger = logging.getLogger(__name__)


@api_view(["POST"])
def create_connection(request):
    ser = ConnectionCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data

    creds = S3Credentials(
        access_key=data["access_key"],
        secret_key=data["secret_key"],
        bucket=data["bucket"],
        region=data["region"] or settings.AWS_DEFAULT_REGION,
        endpoint_url=settings.S3_ENDPOINT_URL,
    )
    S3Service(creds).validate()  # raises a typed AppError on failure
    connection_id, expires_at = store.save(creds)
    logger.info("S3 connection established bucket=%s key_hint=%s", creds.bucket, creds.access_key_hint)
    return Response(
        {
            "connection_id": connection_id,
            "bucket": creds.bucket,
            "region": creds.region,
            "access_key_hint": creds.access_key_hint,
            "expires_at": expires_at.isoformat(),
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET", "DELETE"])
def connection_detail(request, connection_id):
    if request.method == "DELETE":
        store.delete(connection_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
    creds = store.load(connection_id)
    return Response(
        {
            "connection_id": str(connection_id),
            "bucket": creds.bucket,
            "region": creds.region,
            "access_key_hint": creds.access_key_hint,
        }
    )


@api_view(["GET"])
def list_files(request, connection_id):
    q = FileListQuerySerializer(data=request.query_params)
    q.is_valid(raise_exception=True)
    creds = store.load(connection_id)
    files = S3Service(creds).list_files(prefix=q.validated_data["prefix"])
    store.touch(connection_id)
    return Response(
        {
            "bucket": creds.bucket,
            "files": [
                {"key": f.key, "size": f.size, "last_modified": f.last_modified.isoformat(), "kind": f.kind}
                for f in files
            ],
        }
    )


@api_view(["GET"])
def file_schema(request, connection_id):
    q = SchemaQuerySerializer(data=request.query_params)
    q.is_valid(raise_exception=True)
    creds = store.load(connection_id)
    preview = S3Service(creds).preview_schema(q.validated_data["key"])
    return Response(
        {
            "key": q.validated_data["key"],
            "columns": preview.columns,
            "sample_rows": preview.sample_rows,
            "sampled_rows": preview.sampled_rows,
        }
    )
