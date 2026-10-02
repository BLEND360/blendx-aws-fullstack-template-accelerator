import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app.clients import aws
from app.core import errors
from app.main import app
from app.routers.health import readiness_service
from app.services.readiness import ReadinessService


class FakeProbe:
    def __init__(self, name, error=None):
        self.name, self.error, self.calls = name, error, 0

    def check(self):
        self.calls += 1
        if self.error:
            raise self.error


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(probes):
    app.dependency_overrides[readiness_service] = lambda: ReadinessService(probes)


def test_health_touches_nothing(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_ok(client):
    use([FakeProbe("harness"), FakeProbe("table:test-sessions")])
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert [c["name"] for c in response.json()["checks"]] == ["harness", "table:test-sessions"]


def test_ready_degraded_reports_code_not_detail(client):
    down = errors.UnavailableError("x", dependency=errors.HARNESS, detail="arn:aws:secret")
    use([FakeProbe("harness", down), FakeProbe("table:test-sessions")])
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"][0] == {
        "name": "harness", "status": "unavailable", "code": "harness_unavailable",
        "latencyMs": response.json()["checks"][0]["latencyMs"],
    }
    assert "arn:aws" not in response.text


def test_readiness_cached():
    probe, now = FakeProbe("harness"), [0.0]
    service = ReadinessService([probe], clock=lambda: now[0])
    service.report()
    service.report()
    assert probe.calls == 1
    now[0] = ReadinessService.CACHE_SECONDS
    service.report()
    assert probe.calls == 2


def test_default_probes_cover_harness_and_both_tables():
    names = [p.name for p in readiness_service()._probes]
    assert names == ["harness", "table:test-sessions", "table:test-items"]


def test_harness_probe_without_arn_is_misconfigured():
    with pytest.raises(errors.MisconfiguredError) as exc:
        aws.HarnessProbe("").check()
    assert exc.value.code == "harness_misconfigured"


def test_table_probe_classifies_aws_errors(monkeypatch):
    class Denied:
        def describe_table(self, **_):
            raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "DescribeTable")

    monkeypatch.setattr(aws, "client", lambda *a, **k: Denied())
    with pytest.raises(errors.AppError) as exc:
        aws.TableProbe("t").check()
    assert exc.value.code == "data_misconfigured"
