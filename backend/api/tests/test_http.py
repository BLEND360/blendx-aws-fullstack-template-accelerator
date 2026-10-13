"""Request id, logging, error shape, CORS: the cross-cutting behavior of every route."""

import logging

import pytest
from botocore.exceptions import ClientError
from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core import errors
from app.core.context import REQUEST_ID_HEADER
from app.core.logging import get_logger
from app.main import app
from app.routers.dependencies import User, current_user

ORIGIN = "http://localhost:5173"
UPSTREAM_SECRET = "arn:aws:iam::123456789012:role/secret-role is not authorized"
log = get_logger("tests")


class Body(BaseModel):
    count: int


# Test-only routes: each raises one kind of failure.
@app.get("/_t/sync-log")
def _sync_log() -> dict:  # sync: FastAPI runs it in a worker thread
    log.info("from_worker_thread")
    return {}


@app.get("/_t/app-error")
def _app_error() -> None:
    raise errors.ThrottledError("The data store is busy.", dependency=errors.DATA, detail=UPSTREAM_SECRET)


@app.get("/_t/aws-error")
def _aws_error() -> None:
    exc = ClientError({"Error": {"Code": "AccessDeniedException", "Message": UPSTREAM_SECRET}}, "GetItem")
    raise errors.classify_aws_error(exc, dependency=errors.DATA)


@app.get("/_t/crash")
def _crash() -> None:
    raise RuntimeError(UPSTREAM_SECRET)


@app.post("/_t/validate")
def _validate(body: Body) -> dict:
    return {}


@app.get("/_t/me")
def _me(user: User = Depends(current_user)) -> dict:
    return {"id": user.id}


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_request_id_generated_and_returned(client):
    response = client.get("/health")
    assert len(response.headers[REQUEST_ID_HEADER]) == 32


def test_inbound_request_id_echoed(client):
    assert client.get("/health", headers={REQUEST_ID_HEADER: "abc-123"}).headers[REQUEST_ID_HEADER] == "abc-123"


def test_unsafe_request_id_replaced(client):
    forged = 'x"\n{"level":"ERROR"}'
    assert client.get("/health", headers={REQUEST_ID_HEADER: forged}).headers[REQUEST_ID_HEADER] != forged


def test_request_id_exposed_to_browser_js(client):
    response = client.get("/health", headers={"Origin": ORIGIN})
    assert REQUEST_ID_HEADER in response.headers["access-control-expose-headers"]


def test_log_lines_from_worker_thread_carry_request_id(client, caplog):
    with caplog.at_level(logging.INFO):
        client.get("/_t/sync-log", headers={REQUEST_ID_HEADER: "rid-thread"})
    record = next(r for r in caplog.records if r.getMessage() == "from_worker_thread")
    assert record.request_id == "rid-thread"
    access = next(r for r in caplog.records if r.getMessage() == "request_completed")
    assert access.request_id == "rid-thread"


def test_app_error_shape_and_no_upstream_text(client):
    response = client.get("/_t/app-error", headers={REQUEST_ID_HEADER: "rid-1"})
    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "data_throttled", "message": "The data store is busy.", "retryable": True,
                  "requestId": "rid-1"}
    }


def test_aws_error_classified_without_leaking(client):
    response = client.get("/_t/aws-error")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "data_misconfigured"
    assert "arn:aws" not in response.text


def test_unhandled_error_is_generic_and_keeps_cors_and_request_id(client):
    response = client.get("/_t/crash", headers={"Origin": ORIGIN, REQUEST_ID_HEADER: "rid-500"})
    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "internal_error", "message": "The request could not be completed.", "retryable": False,
        "requestId": "rid-500",
    }
    assert "arn:aws" not in response.text
    # CORS is outermost, so the browser can read this 500 instead of seeing a CORS failure.
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers[REQUEST_ID_HEADER] == "rid-500"


def test_validation_error_shape(client):
    body = client.post("/_t/validate", json={"count": "not-a-number"}).json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["fields"][0]["location"] == "body.count"
    assert "not-a-number" not in str(body)


def test_unknown_route_uses_same_shape(client):
    assert client.get("/nope").json()["error"]["code"] == "not_found"


def test_authenticated_route_refused_without_bypass(client):
    response = client.get("/_t/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_invalid_token"


def test_authenticated_route_served_with_local_bypass(client, monkeypatch):
    from app.routers import dependencies

    monkeypatch.setattr(dependencies.settings, "local_auth_bypass", True)
    assert client.get("/_t/me").json() == {"id": dependencies.settings.local_auth_user_id}


@pytest.mark.parametrize(
    "code,expected",
    [
        ("ThrottlingException", "harness_throttled"),
        ("ServiceUnavailableException", "harness_unavailable"),
        ("ResourceNotFoundException", "harness_misconfigured"),
        ("ValidationException", "harness_invalid_request"),
        ("ConditionalCheckFailedException", "harness_conflict"),
        ("SomethingNew", "harness_error"),
    ],
)
def test_classification(code, expected):
    exc = ClientError({"Error": {"Code": code, "Message": UPSTREAM_SECRET}}, "Op")
    classified = errors.classify_aws_error(exc, dependency=errors.HARNESS)
    assert classified.code == expected
    assert UPSTREAM_SECRET not in classified.message
