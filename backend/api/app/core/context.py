"""Per-request correlation id.

One id follows a request through every log line it produces and comes back to
the caller in `X-Request-Id` and in the body of any error. Held in a
ContextVar because logging needs it and cannot take a request parameter at
every call site. Starlette's threadpool copies the context, so sync endpoints
and `run_in_threadpool` log with the id too; a raw `threading.Thread` must
re-bind it (the harness client does, ST-06).
"""

import contextvars
import re
import uuid

REQUEST_ID_HEADER = "X-Request-Id"

# An inbound id is echoed into logs and bodies, so it is untrusted input:
# bounded, and nothing that could forge a log line or a header. A bad one is
# replaced rather than rejected; the request is still served.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def sanitize_request_id(candidate: str | None) -> str:
    if candidate is not None and _SAFE_REQUEST_ID.match(candidate.strip()):
        return candidate.strip()
    return uuid.uuid4().hex


def bind_request_id(request_id: str) -> contextvars.Token:
    return _request_id.set(request_id)


def reset_request_id(token: contextvars.Token) -> None:
    _request_id.reset(token)


def get_request_id() -> str | None:
    return _request_id.get()
