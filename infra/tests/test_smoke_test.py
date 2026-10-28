import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import smoke_test
from awsutil import DeployError


def test_accepts_only_successful_json_health_body():
    assert smoke_test.is_healthy(200, "application/json", b'{"status":"ok"}')
    assert not smoke_test.is_healthy(200, "text/html", b"<html>")
    assert not smoke_test.is_healthy(200, "application/json", b'{"status":"down"}')
    assert not smoke_test.is_healthy(502, "application/json", b'{"status":"ok"}')
    assert not smoke_test.is_healthy(200, "application/json", b"not json")


def test_retries_transient_errors_then_succeeds(monkeypatch):
    responses = iter([(502, "text/html", b"bad gateway"), (200, "application/json", b'{"status":"ok"}')])
    sleeps = []
    monkeypatch.setattr(smoke_test, "request", lambda _url: next(responses))
    monkeypatch.setattr(smoke_test.time, "sleep", sleeps.append)
    times = iter([0, 0, 1])
    monkeypatch.setattr(smoke_test.time, "monotonic", lambda: next(times))

    smoke_test.wait_for_health("https://example.test/api/health", timeout=5, interval=1)
    assert sleeps == [1]


def test_reports_url_status_and_limited_body_when_timeout(monkeypatch):
    monkeypatch.setattr(smoke_test, "request", lambda _url: (502, "text/html", b"x" * 250))
    times = iter([0, 0, 6])
    monkeypatch.setattr(smoke_test.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(smoke_test.time, "sleep", lambda _seconds: None)

    with pytest.raises(DeployError) as error:
        smoke_test.wait_for_health("https://example.test/api/health", timeout=5, interval=1)
    message = str(error.value)
    assert "https://example.test/api/health" in message
    assert "502" in message
    assert "x" * 201 not in message


def test_body_parser_requires_json_object_status_ok():
    assert not smoke_test.is_healthy(200, "application/json", json.dumps(["ok"]).encode())
