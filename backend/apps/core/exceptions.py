"""
Application error type and the DRF exception handler that renders it.

Every error the API returns has the shape {"code": "...", "message": "..."} so the
frontend can branch on `code` and show `message` to the user.
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Domain error carrying a machine-readable code and an HTTP status."""

    code = "APP_ERROR"
    http_status = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, *, code: str | None = None, http_status: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if http_status:
            self.http_status = http_status

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


class NotFound(AppError):
    code = "NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND


class Conflict(AppError):
    code = "CONFLICT"
    http_status = status.HTTP_409_CONFLICT


def api_exception_handler(exc, context):
    if isinstance(exc, AppError):
        return Response(exc.to_dict(), status=exc.http_status)

    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled exception in %s", context.get("view"))
        return Response(
            {"code": "INTERNAL_ERROR", "message": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, ValidationError):
        response.data = {"code": "VALIDATION_ERROR", "message": "Invalid input.", "details": response.data}
    elif isinstance(exc, APIException):
        response.data = {"code": exc.default_code.upper(), "message": str(exc.detail)}
    return response
