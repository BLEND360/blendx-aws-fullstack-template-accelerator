"""Client configuration and the provisional current-user endpoint."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import dependencies


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def bypass(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "local_auth_bypass", True)


def test_configuration_requires_a_user(client):
    response = client.get("/api/v1/configuration")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_invalid_token"


def test_configuration_lists_models_and_default(client, bypass, monkeypatch):
    monkeypatch.setattr(dependencies.settings, "allowed_model_ids", ["model-a", "model-b"])
    response = client.get("/api/v1/configuration")
    assert response.status_code == 200
    assert response.json() == {"allowedModelIds": ["model-a", "model-b"], "defaultModelId": "model-a"}


def test_configuration_exposes_nothing_but_display_values(client, bypass):
    # A closed response model: adding a field means editing it on purpose.
    assert set(client.get("/api/v1/configuration").json()) == {"allowedModelIds", "defaultModelId"}


def test_me_requires_a_user(client):
    assert client.get("/auth/me").status_code == 401


def test_me_returns_the_local_bypass_user(client, bypass):
    response = client.get("/auth/me")
    assert response.status_code == 200
    assert response.json() == {
        "id": dependencies.settings.local_auth_user_id,
        "name": dependencies.settings.local_auth_user_name,
        "email": dependencies.settings.local_auth_user_email,
        "roles": [],
    }
