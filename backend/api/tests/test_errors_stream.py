"""Error taxonomy for memory, in-stream failures, not-found and validation."""

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError
from fastapi.testclient import TestClient

from app.core import config, errors
from app.core.context import REQUEST_ID_HEADER
from app.main import app

SECRET = "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/secret-mem-1234567890 denied"


def aws(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": SECRET}}, "Op")


@pytest.mark.parametrize(
    "aws_code,expected",
    [
        ("ThrottledException", "memory_throttled"),  # memory's spelling of throttling
        ("InvalidInputException", "memory_invalid_request"),
        ("ServiceException", "memory_unavailable"),
        ("ResourceNotFoundException", "memory_misconfigured"),
        ("AccessDeniedException", "memory_misconfigured"),
        ("SomethingNew", "memory_error"),
    ],
)
def test_memory_codes(aws_code, expected):
    classified = errors.classify_aws_error(aws(aws_code), dependency=errors.MEMORY)
    assert classified.code == expected
    assert "arn:aws" not in classified.message


def test_invoke_runtime_client_error_is_a_harness_availability_problem():
    classified = errors.classify_aws_error(aws("RuntimeClientError"), dependency=errors.HARNESS)
    assert (classified.code, classified.retryable) == ("harness_unavailable", True)


@pytest.mark.parametrize(
    "event,code,retryable",
    [
        ("internalServerException", "harness_unavailable", True),
        ("runtimeClientError", "harness_unavailable", True),
        ("validationException", "harness_invalid_request", False),
        ("somethingElse", "harness_error", False),
    ],
)
def test_errors_inside_the_stream(event, code, retryable):
    classified = errors.classify_stream_error(event, detail=SECRET)
    assert (classified.code, classified.retryable) == (code, retryable)
    assert "arn:aws" not in classified.message
    assert classified.detail == SECRET  # for the log, never for the client


@pytest.mark.parametrize(
    "event,code",
    [("internalServerException", "harness_unavailable"), ("validationException", "harness_invalid_request")],
)
def test_botocore_raises_in_stream_errors_as_client_errors(event, code):
    # EventStreamError is how botocore surfaces an error event inside an open stream.
    from botocore.eventstream import EventStreamError

    exc = EventStreamError({"Error": {"Code": event, "Message": SECRET}}, "InvokeHarness")
    classified = errors.classify_aws_error(exc, dependency=errors.HARNESS)
    assert classified.code == code
    assert "arn:aws" not in classified.message


def test_a_response_stream_that_breaks_is_retryable_unavailability():
    from botocore.exceptions import ResponseStreamingError

    classified = errors.classify_aws_error(ResponseStreamingError(error="connection reset"), dependency=errors.HARNESS)
    assert (classified.code, classified.retryable) == ("harness_unavailable", True)


def test_a_read_timeout_is_an_availability_error_not_a_new_code():
    # The list of codes is closed: a timeout is reported as `<dependency>_unavailable`.
    exc = ReadTimeoutError(endpoint_url="https://example.invalid")
    classified = errors.classify_aws_error(exc, dependency=errors.HARNESS)
    assert (classified.code, classified.http_status, classified.retryable) == ("harness_unavailable", 504, True)


# --- not_found and validation, through the one error body -----------------------
@app.get("/_t/missing")
def _missing() -> None:
    raise errors.NotFoundError("Session not found.")


@app.get("/_t/invalid")
def _invalid() -> None:
    raise errors.ValidationFailedError(
        "The request is not valid.", fields=[{"location": "body.modelId", "message": "Model is not allowed."}]
    )


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_not_found_has_the_single_error_shape(client):
    response = client.get("/_t/missing", headers={REQUEST_ID_HEADER: "rid-nf"})
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Session not found.", "retryable": False, "requestId": "rid-nf"}
    }


def test_validation_failure_carries_its_fields(client):
    response = client.get("/_t/invalid", headers={REQUEST_ID_HEADER: "rid-v"})
    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "validation_error",
        "message": "The request is not valid.",
        "retryable": False,
        "requestId": "rid-v",
        "fields": [{"location": "body.modelId", "message": "Model is not allowed."}],
    }


# --- settings --------------------------------------------------------------------
def test_new_settings_have_defaults_so_existing_deployments_start_unchanged(monkeypatch):
    for var in ("HARNESS_IDLE_TIMEOUT_SECONDS", "HARNESS_TURN_TIMEOUT_SECONDS", "MAX_TOOL_ROUNDS"):
        monkeypatch.delenv(var, raising=False)
    loaded = config.load_settings()
    assert (loaded.harness_idle_timeout_seconds, loaded.harness_turn_timeout_seconds, loaded.max_tool_rounds) == (
        300, 900, 8,
    )


def test_new_settings_can_be_overridden(monkeypatch):
    monkeypatch.setenv("HARNESS_IDLE_TIMEOUT_SECONDS", "45")
    assert config.load_settings().harness_idle_timeout_seconds == 45
