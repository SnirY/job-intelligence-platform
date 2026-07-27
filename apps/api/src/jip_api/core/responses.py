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


class PaginationMeta(BaseModel):
    """Collection pagination metadata from ``docs/10-api-contracts.md``."""

    page: int
    page_size: int
    total: int
    total_pages: int


class CollectionResponse[T](BaseModel):
    """Standard collection success envelope.

    Separate from :class:`DataResponse` because a paginated list has to carry
    the counts the caller needs to page through it; folding them into `data`
    would make every list payload a different shape.
    """

    data: list[T]
    meta: PaginationMeta
