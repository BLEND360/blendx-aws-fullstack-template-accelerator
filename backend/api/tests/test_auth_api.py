"""Sign-in over HTTP: login, me, a protected route, role guard, and the local bypass."""

import logging

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.clients.session_tokens import SessionTokenCodec
from app.core.errors import InvalidTokenError
from app.core.exception_handlers import register_exception_handlers
from app.main import app
from app.routers import dependencies as deps
from app.services.auth import AuthService
from app.core.models import Identity, SessionClaims

SECRET = "s" * 32


class FakeVerifier:
    def __init__(self, groups=("admin",)):
        self.groups = groups

    def verify(self, id_token):
        if id_token != "cognito-id-token":
            raise InvalidTokenError(detail="id token rejected: bad")
        return Identity("u-1", "u@example.test", "U One", self.groups)


def codec(ttl=3600):
    return SessionTokenCodec(SECRET, "test-project", ttl)


@pytest.fixture
def make_client():
    def build(groups=("admin",), ttl=3600):
        service = AuthService(FakeVerifier(groups), codec(ttl))
        app.dependency_overrides[deps.auth_service] = lambda: service
        return TestClient(app, raise_server_exceptions=False)

    yield build
    app.dependency_overrides.clear()


def login(client, token="cognito-id-token"):
    return client.post("/auth/login", json={"id_token": token})


def test_login_then_me_returns_the_profile_with_roles(make_client):
    client = make_client(("admin", "user"))
    body = login(client).json()
    assert body["user"] == {"id": "u-1", "name": "U One", "email": "u@example.test", "roles": ["admin", "user"]}
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json() == body["user"]


def test_the_credential_opens_authenticated_routes(make_client):
    client = make_client()
    token = login(client).json()["access_token"]
    assert client.get("/api/v1/items", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/api/v1/items").status_code == 401


def test_a_rejected_id_token_is_401_and_issues_nothing(make_client):
    response = login(make_client(), token="forged")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_invalid_token"
    assert "access_token" not in response.text


def test_manipulated_and_expired_credentials_are_401(make_client):
    client = make_client()
    good = login(client).json()["access_token"]
    for bad in (good[:-3] + "abc", codec(ttl=-5).issue(SessionClaims("u-1", "", "", ()))):
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {bad}"})
        assert response.status_code == 401, bad
        assert response.json()["error"]["code"] == "auth_invalid_token"


def test_cognitos_own_token_is_not_a_session(make_client):
    response = make_client().get("/auth/me", headers={"Authorization": "Bearer cognito-id-token"})
    assert response.status_code == 401


def test_login_without_cognito_configured_is_503():
    app.dependency_overrides[deps.auth_service] = lambda: AuthService(None, None)
    try:
        response = TestClient(app, raise_server_exceptions=False).post("/auth/login", json={"id_token": "x"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_unavailable"


def test_a_failed_login_never_logs_the_token(make_client, caplog):
    secret_token = "eyJ-very-secret-token"
    with caplog.at_level(logging.DEBUG):
        login(make_client(), token=secret_token)
    assert secret_token not in caplog.text


def guarded_app(groups):
    sub = FastAPI()
    register_exception_handlers(sub)

    @sub.get("/admin-only")
    def admin_only(user: deps.User = Depends(deps.require_role("admin"))):
        return {"who": user.id}

    service = AuthService(FakeVerifier(groups), codec())
    sub.dependency_overrides[deps.auth_service] = lambda: service
    return TestClient(sub, raise_server_exceptions=False), service.login("cognito-id-token")[0]


def test_role_guard_admits_the_role_and_refuses_others_with_403():
    client, token = guarded_app(("admin",))
    assert client.get("/admin-only", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    client, token = guarded_app(("user",))
    denied = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "auth_forbidden"
    assert client.get("/admin-only").status_code == 401


def test_local_bypass_serves_the_stand_in_user_and_warns(monkeypatch, caplog):
    monkeypatch.setattr(deps.settings, "local_auth_bypass", True)
    with caplog.at_level(logging.WARNING):
        response = TestClient(app).get("/auth/me")
    assert response.status_code == 200 and response.json()["id"] == "local-dev-user"
    assert "local_auth_bypass_used" in caplog.text
