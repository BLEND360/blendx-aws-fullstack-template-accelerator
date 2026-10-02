import pytest

from app.core import config


def test_missing_variable_fails_at_startup_with_its_name(monkeypatch):
    monkeypatch.delenv("SESSIONS_TABLE_NAME")
    monkeypatch.chdir("tests")  # no .env here to fill the gap
    with pytest.raises(config.SettingsError, match="SESSIONS_TABLE_NAME"):
        config.load_settings()


@pytest.mark.parametrize("origins", ["", "*", "http://localhost:5173,*"])
def test_cors_must_be_exact_origins(monkeypatch, origins):
    monkeypatch.setenv("CORS_ORIGINS", origins)
    with pytest.raises(config.SettingsError, match="CORS_ORIGINS"):
        config.load_settings()


def test_empty_model_allowlist_rejected(monkeypatch):
    monkeypatch.setenv("ALLOWED_MODEL_IDS", "[]")
    with pytest.raises(config.SettingsError, match="ALLOWED_MODEL_IDS"):
        config.load_settings()


def test_auth_bypass_ignored_in_a_deployed_task(monkeypatch):
    monkeypatch.setenv("LOCAL_AUTH_BYPASS", "true")
    assert config.load_settings().auth_bypass_enabled
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI_V4", "http://169.254.170.2/v4/abc")
    assert not config.load_settings().auth_bypass_enabled
