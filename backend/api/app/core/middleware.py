"""Correlation id and the access log: one line per request, with its id."""

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.context import REQUEST_ID_HEADER, bind_request_id, reset_request_id, sanitize_request_id
from app.core.errors import internal_error_payload
from app.core.logging import get_logger

logger = get_logger("app.access")

# Polled every few seconds by the ALB; logging each one buries real traffic.
_UNLOGGED_PATHS = frozenset({"/health"})


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Take `X-Request-Id` from the caller when usable, else generate one; echo it always."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = sanitize_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = bind_request_id(request_id)
        started = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                # Escaped FastAPI's own handlers. Answering rather than
                # re-raising guarantees the caller still gets the id.
                logger.exception("request_failed", method=request.method, path=request.url.path)
                response = JSONResponse(status_code=500, content=internal_error_payload())
            response.headers[REQUEST_ID_HEADER] = request_id
            if request.url.path not in _UNLOGGED_PATHS:
                logger.info(
                    "request_completed",
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )
            return response
        finally:
            reset_request_id(token)
