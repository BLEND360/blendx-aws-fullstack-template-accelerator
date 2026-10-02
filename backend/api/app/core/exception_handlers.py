"""Every error response is produced here, in the shape from core/errors.py.

Registered rather than left to FastAPI's defaults because the defaults publish
whatever `detail` a raise site passed.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.core.context import REQUEST_ID_HEADER, get_request_id
from app.core.errors import AppError, error_payload, internal_error_payload
from app.core.logging import get_logger

logger = get_logger(__name__)

# `detail` on an HTTPException raised in this codebase is a short, reviewed
# sentence, and Starlette's own (404, 405) are equally safe to return.
_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    429: "rate_limited",
}


def _json(status_code: int, payload: dict) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content=payload)
    if request_id := get_request_id():
        response.headers[REQUEST_ID_HEADER] = request_id
    return response


async def _app_error(request: Request, exc: AppError) -> JSONResponse:
    log = logger.warning if exc.http_status < 500 else logger.error
    # The upstream text goes here, and nowhere else.
    log("app_error", code=exc.code, status_code=exc.http_status, path=request.url.path, detail=exc.detail)
    return _json(exc.http_status, exc.to_payload())


async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    response = _json(
        exc.status_code,
        error_payload(code=_HTTP_CODES.get(exc.status_code, "http_error"), message=message,
                      retryable=exc.status_code in (429, 503)),
    )
    for header, value in (exc.headers or {}).items():  # keep WWW-Authenticate challenges
        response.headers[header] = value
    return response


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Per-field errors describe the caller's own payload, so they are safe.
    # `input` is dropped: it can be the user's message text.
    fields = [
        {"location": ".".join(map(str, e.get("loc", ()))), "message": e.get("msg", "invalid value")}
        for e in exc.errors()
    ]
    return _json(
        422, error_payload(code="validation_error", message="The request payload is not valid.", fields=fields)
    )


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", method=request.method, path=request.url.path)
    return _json(500, internal_error_payload())


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unexpected_error)
