"""Response envelopes defined in ``docs/10-api-contracts.md``.

Successful responses wrap their payload in ``data``; errors wrap theirs in
``error``. Keeping the shapes here means individual routers never hand-roll the
envelope.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DataResponse[T](BaseModel):
    """Standard single-resource success envelope."""

    data: T


class ErrorBody(BaseModel):
    """Machine-readable error description."""

    code: str
    message: str
    details: Any | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """Standard error envelope."""

    error: ErrorBody
