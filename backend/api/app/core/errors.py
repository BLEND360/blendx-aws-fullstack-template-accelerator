"""The error taxonomy and its one response shape.

Two rules:

1. Nothing a dependency says reaches the client. A botocore message carries
   ARNs, account ids and fragments of the request. Every error leaving the
   process is a fixed sentence plus a stable code; the real cause is logged
   against the request id.
2. A failure is attributed to the dependency that produced it. The code is
   `<dependency>_<category>` (`harness_unavailable`, `data_throttled`), so the
   client can decide whether to offer a retry without parsing prose.

Repositories and clients translate AWS errors with `classify_aws_error`;
services and routers only ever see `AppError`.
"""

from typing import Any

from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
)
from botocore.exceptions import ConnectionError as BotoConnectionError

from app.core.context import get_request_id

# Part of the codes the client matches on, so constants, not free-form strings.
HARNESS = "harness"
MEMORY = "memory"
TOOL = "tool"
DATA = "data"
AUTH = "auth"

_LABELS = {
    HARNESS: "the assistant",
    MEMORY: "conversation history",
    TOOL: "a tool",
    DATA: "the data store",
    AUTH: "sign-in",
}


class AppError(Exception):
    """An error with a client-safe rendering. `detail` is logged, never serialized."""

    category = "error"
    http_status = 502
    retryable = False

    def __init__(self, message: str, *, dependency: str | None = None, detail: str | None = None) -> None:
        super().__init__(detail or message)
        self.message = message
        self.dependency = dependency
        self.detail = detail

    @property
    def code(self) -> str:
        return f"{self.dependency}_{self.category}" if self.dependency else self.category

    def to_payload(self) -> dict[str, Any]:
        return error_payload(code=self.code, message=self.message, retryable=self.retryable)


class MisconfiguredError(AppError):
    """The deployment is wrong (an unset ARN, a missing grant's credentials).

    500, so it shows in error-rate alarms instead of hiding among client errors.
    """

    category = "misconfigured"
    http_status = 500


class UnavailableError(AppError):
    category = "unavailable"
    http_status = 503
    retryable = True


class ThrottledError(AppError):
    category = "throttled"
    http_status = 503
    retryable = True


class TimeoutError_(AppError):
    category = "timeout"
    http_status = 504
    retryable = True


class InvalidRequestError(AppError):
    """The upstream rejected what this service sent: our bug, not the caller's."""

    category = "invalid_request"
    http_status = 502


class ConflictError(AppError):
    """A write lost an optimistic-concurrency race; the caller should re-read."""

    category = "conflict"
    http_status = 409


class ToolFailedError(AppError):
    category = "failed"
    http_status = 502


class InvalidTokenError(AppError):
    category = "invalid_token"
    http_status = 401

    def __init__(self, message: str = "Sign in again to continue.", **kwargs: Any) -> None:
        super().__init__(message, dependency=AUTH, **kwargs)


class ForbiddenError(AppError):
    category = "forbidden"
    http_status = 403


# botocore error codes -> (class, sentence). The specific code goes to the log.
_BUSY = "{Label} is busy. Try again in a moment."
_DOWN = "{Label} is temporarily unavailable."
_CLIENT_ERRORS: dict[str, tuple[type[AppError], str]] = {
    # The task role lacks a permission: a deployment fault, never the user's.
    "AccessDeniedException": (MisconfiguredError, "The service is not permitted to reach {label}."),
    "AccessDenied": (MisconfiguredError, "The service is not permitted to reach {label}."),
    "UnrecognizedClientException": (MisconfiguredError, "The service is not permitted to reach {label}."),
    "ResourceNotFoundException": (MisconfiguredError, "{Label} is not set up for this deployment."),
    "ThrottlingException": (ThrottledError, _BUSY),
    "TooManyRequestsException": (ThrottledError, _BUSY),
    "ProvisionedThroughputExceededException": (ThrottledError, _BUSY),
    "RequestLimitExceeded": (ThrottledError, _BUSY),
    "ServiceQuotaExceededException": (ThrottledError, _BUSY),
    "ValidationException": (InvalidRequestError, "{Label} rejected the request."),
    "ConditionalCheckFailedException": (ConflictError, "This item changed since you loaded it. Reload and try again."),
    "TransactionConflictException": (ConflictError, "This item changed since you loaded it. Reload and try again."),
    "ServiceUnavailableException": (UnavailableError, _DOWN),
    "InternalServerException": (UnavailableError, _DOWN),
    "InternalServerError": (UnavailableError, _DOWN),
    "ModelNotReadyException": (UnavailableError, "{Label} is still warming up. Try again in a moment."),
    "ModelTimeoutException": (TimeoutError_, "{Label} took too long to respond."),
    "RequestTimeout": (TimeoutError_, "{Label} took too long to respond."),
}


def classify_aws_error(exc: BaseException, *, dependency: str) -> AppError:
    """Translate a boto3/botocore failure into a typed, client-safe error.

    Anything unrecognized becomes a generic 502 rather than escaping untyped,
    which is what used to leak its message.
    """
    if isinstance(exc, AppError):
        return exc
    label = _LABELS.get(dependency, dependency)
    fmt = {"label": label, "Label": label[:1].upper() + label[1:]}

    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
        cls, sentence = _CLIENT_ERRORS.get(code, (AppError, "{Label} returned an unexpected error."))
        return cls(sentence.format(**fmt), dependency=dependency, detail=f"{code}: {exc}")
    if isinstance(exc, (ConnectTimeoutError, ReadTimeoutError)):
        return TimeoutError_("{Label} took too long to respond.".format(**fmt), dependency=dependency, detail=str(exc))
    if isinstance(exc, (EndpointConnectionError, BotoConnectionError)):
        return UnavailableError("{Label} could not be reached.".format(**fmt), dependency=dependency, detail=str(exc))
    if isinstance(exc, NoCredentialsError):
        return MisconfiguredError(
            "The service is not configured to reach {label}.".format(**fmt), dependency=dependency, detail=str(exc)
        )
    detail = str(exc) if isinstance(exc, BotoCoreError) else f"{type(exc).__name__}: {exc}"
    return AppError("{Label} returned an unexpected error.".format(**fmt), dependency=dependency, detail=detail)


def error_payload(*, code: str, message: str, retryable: bool = False, **extra: Any) -> dict[str, Any]:
    """The one error body this API emits."""
    return {"error": {"code": code, "message": message, "retryable": retryable, "requestId": get_request_id(), **extra}}


def internal_error_payload() -> dict[str, Any]:
    """For an exception nobody reviewed for what it discloses: say nothing specific."""
    return error_payload(code="internal_error", message="The request could not be completed.")
