from rest_framework import status

from apps.core.exceptions import AppError


class ConnectionError_(AppError):
    """Base for S3 connection problems (HTTP 400 unless overridden)."""


class InvalidCredentials(ConnectionError_):
    code = "INVALID_CREDENTIALS"


class AccessDenied(ConnectionError_):
    code = "ACCESS_DENIED"
    http_status = status.HTTP_403_FORBIDDEN


class BucketNotFound(ConnectionError_):
    code = "BUCKET_NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND


class S3Unreachable(ConnectionError_):
    code = "NETWORK_ERROR"
    http_status = status.HTTP_502_BAD_GATEWAY


class ConnectionExpired(ConnectionError_):
    code = "CONNECTION_EXPIRED"
    http_status = status.HTTP_404_NOT_FOUND


class UnsupportedFile(ConnectionError_):
    code = "UNSUPPORTED_FILE"


class FileNotFound(ConnectionError_):
    code = "FILE_NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND
