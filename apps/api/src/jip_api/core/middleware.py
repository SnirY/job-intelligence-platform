"""HTTP middleware for request correlation."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from jip_api.core.context import REQUEST_ID_HEADER, set_request_id


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id and echo it back on the response.

    An inbound ``X-Request-ID`` is reused so a correlation id set by a proxy or
    the frontend survives across the hop; otherwise a UUID is generated.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        set_request_id(request_id)
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
