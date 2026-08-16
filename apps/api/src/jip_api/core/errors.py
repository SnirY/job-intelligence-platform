"""Application errors and the handlers that map them onto the error envelope.

Internal failure detail never reaches the client: unhandled exceptions are
logged with their traceback and returned as a generic ``INTERNAL_ERROR``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from jip_api.application.applications.service import TransitionNotAllowedError
from jip_api.application.career.skills import BlankEvidenceError
from jip_api.application.documents.upload import UploadRejected
from jip_api.application.errors import (
    ApplicationError,
    DuplicateResourceError,
    ResourceNotFoundError,
)
from jip_api.application.processing.jobs import JobNotRetriableError
from jip_api.application.resumes.authoring import (
    ResumeFamilyError,
    ResumeNotEditableError,
)
from jip_api.application.resumes.confirm import InvalidDecisionError
from jip_api.application.resumes.tailoring_service import StrategyNotPossibleError
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
        code: str | None = None,
        details: Any | None = None,
    ) -> None:
        super().__init__(message or self.message)
        if message is not None:
            self.message = message
        if code is not None:
            # Overridable for the same reason `message` is: one status can carry
            # several distinguishable refusals, and a client that has to match
            # on prose to tell them apart will break the first time the prose
            # is improved.
            self.code = code
        self.details = details


class ServiceUnavailableError(APIError):
    """A required downstream dependency is not usable right now."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_UNAVAILABLE"
    message = "A required dependency is unavailable."


class NotFoundError(APIError):
    """The requested resource does not exist for this caller."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message = "The requested resource could not be found."


class ConflictError(APIError):
    """The request collides with an existing resource."""

    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"
    message = "The request conflicts with existing data."


class UnprocessableEntityError(APIError):
    """Well-formed, and not something we will act on.

    Distinct from the 422 FastAPI raises for a schema violation: the body parsed
    and every field is the right shape. What is refused is what the values
    *mean* — an address inside the private network is a valid URL and still one
    we will never fetch (DEV-041).
    """

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "UNPROCESSABLE"
    message = "That request cannot be acted on."


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
        # jsonable_encoder is required, not cosmetic: when a custom
        # field_validator raises ValueError, pydantic puts that exception object
        # into ctx, and serialising it directly fails — turning every such 422
        # into a 500.
        details=jsonable_encoder(exc.errors()),
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


async def _handle_application_error(_: Request, exc: Exception) -> JSONResponse:
    """Map a use-case failure onto the error envelope.

    Keeps the application layer free of any HTTP dependency: it raises a
    domain-shaped error and the status code is decided here.
    """
    assert isinstance(exc, ApplicationError)
    mapped = _APPLICATION_ERROR_MAP.get(type(exc))
    if mapped is None:
        raise exc  # unmapped: let the generic 500 handler log it properly

    status_code, code = mapped
    return error_response(status_code=status_code, code=code, message=str(exc) or code)


_APPLICATION_ERROR_MAP: dict[type[ApplicationError], tuple[int, str]] = {
    ResourceNotFoundError: (status.HTTP_404_NOT_FOUND, "NOT_FOUND"),
    DuplicateResourceError: (status.HTTP_409_CONFLICT, "CONFLICT"),
    # A stated reason that is blank once trimmed. The request is malformed
    # rather than in conflict with anything, and the route's own constraint
    # normally catches it first.
    BlankEvidenceError: (HTTP_422_UNPROCESSABLE_CONTENT, "UNPROCESSABLE_ENTITY"),
    # An unacceptable upload is the caller's request being wrong, not a server
    # fault, and the message is written to be shown to the person who chose the
    # file.
    UploadRejected: (HTTP_422_UNPROCESSABLE_CONTENT, "UPLOAD_REJECTED"),
    # Retrying a job that cannot be retried is a conflict with its current
    # state, which is what 409 means.
    JobNotRetriableError: (status.HTTP_409_CONFLICT, "CONFLICT"),
    # An item id that is not part of this extraction. Reported as not found,
    # for the same reason every other cross-user lookup is: distinguishing
    # "not yours" from "does not exist" is an enumeration oracle.
    InvalidDecisionError: (status.HTTP_404_NOT_FOUND, "NOT_FOUND"),
    # A family and a job that contradict each other: the request itself cannot
    # describe a resume that could exist, which is what 422 means.
    ResumeFamilyError: (HTTP_422_UNPROCESSABLE_CONTENT, "INVALID_RESUME_FAMILY"),
    # Editing a used version, or a status transition the lifecycle forbids.
    # A conflict with the resource's current state rather than a malformed
    # request — the same reading as JobNotRetriableError above.
    ResumeNotEditableError: (status.HTTP_409_CONFLICT, "CONFLICT"),
    # Tailoring a job that has never been matched. A precondition that has not
    # been met yet rather than a bad request — the same 409 Phase 6 returns for
    # matching a job that has never been analysed.
    StrategyNotPossibleError: (status.HTTP_409_CONFLICT, "CONFLICT"),
    # A lifecycle move the record forbids. A conflict with the resource's
    # current state, the same reading as every other transition refusal
    # here — and the message is written to be shown to whoever tried it.
    TransitionNotAllowedError: (status.HTTP_409_CONFLICT, "CONFLICT"),
}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the envelope-producing handlers to the application."""
    app.add_exception_handler(ApplicationError, _handle_application_error)
    app.add_exception_handler(APIError, _handle_api_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected_error)
