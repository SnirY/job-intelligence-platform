"""Application errors and the handlers that map them onto the error envelope.

Internal failure detail never reaches the client: unhandled exceptions are
logged with their traceback and returned as a generic ``INTERNAL_ERROR``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from jip_api.core.context import get_request_id
from jip_api.core.responses import ErrorBody, ErrorResponse

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Base class for errors that carry an intentional client-facing contract."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Any | None = None,
    ) -> None:
        super().__init__(message or self.message)
        if message is not None:
            self.message = message
        self.details = details


class ServiceUnavailableError(APIError):
    """A required downstream dependency is not usable right now."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_UNAVAILABLE"
    message = "A required dependency is unavailable."


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
) -> JSONResponse:
    """Build a JSON response using the documented error envelope."""
    payload = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details,
            request_id=get_request_id(),
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


async def _handle_api_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, APIError)
    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


# Starlette renamed HTTP_422_UNPROCESSABLE_ENTITY to HTTP_422_UNPROCESSABLE_CONTENT
# (RFC 9110) and deprecated the old name. Using the literal keeps this working
# across both spellings.
HTTP_422_UNPROCESSABLE_CONTENT = 422


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return error_response(
        status_code=HTTP_422_UNPROCESSABLE_CONTENT,
        code="VALIDATION_ERROR",
        message="The request payload failed validation.",
        details=exc.errors(),
    )


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return error_response(
        status_code=exc.status_code,
        code=_HTTP_ERROR_CODES.get(exc.status_code, "HTTP_ERROR"),
        message=str(exc.detail),
    )


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled exception while handling %s %s", request.method, request.url.path, exc_info=exc
    )
    return error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="INTERNAL_ERROR",
        message="An unexpected error occurred.",
    )


_HTTP_ERROR_CODES: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
    status.HTTP_401_UNAUTHORIZED: "UNAUTHENTICATED",
    status.HTTP_403_FORBIDDEN: "FORBIDDEN",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
    status.HTTP_409_CONFLICT: "CONFLICT",
    status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the envelope-producing handlers to the application."""
    app.add_exception_handler(APIError, _handle_api_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected_error)
