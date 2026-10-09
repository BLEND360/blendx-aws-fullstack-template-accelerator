import pytest

from app.core import config


def test_missing_variable_fails_at_startup_with_its_name(monkeypatch):
    monkeypatch.delenv("SESSIONS_TABLE_NAME")
    monkeypatch.chdir("tests")  # no .env here to fill the gap
    with pytest.raises(config.SettingsError, match="SESSIONS_TABLE_NAME"):
        config.load_settings()


def test_starts_without_any_allowed_origins(monkeypatch):
    # The SPA and the API share an origin, so no origin allowlist exists.
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert config.load_settings().project_name == "test-project"
    assert "cors_origins" not in config.Settings.model_fields


def test_empty_model_allowlist_rejected(monkeypatch):
    monkeypatch.setenv("ALLOWED_MODEL_IDS", "[]")
    with pytest.raises(config.SettingsError, match="ALLOWED_MODEL_IDS"):
        config.load_settings()


def test_auth_bypass_ignored_in_a_deployed_task(monkeypatch):
    monkeypatch.setenv("LOCAL_AUTH_BYPASS", "true")
    assert config.load_settings().auth_bypass_enabled
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI_V4", "http://169.254.170.2/v4/abc")
    assert not config.load_settings().auth_bypass_enabled
