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


def _cognito(monkeypatch, secret="s" * 32):
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-east-1_abc")
    monkeypatch.setenv("COGNITO_APP_CLIENT_ID", "client-1")
    monkeypatch.setenv("AUTH_JWT_SECRET", secret)


def test_auth_is_off_by_default_and_needs_no_secret():
    s = config.load_settings()
    assert not s.cognito_configured
    assert s.auth_token_ttl_seconds == 3600


def test_cognito_with_a_strong_secret_starts(monkeypatch):
    _cognito(monkeypatch)
    assert config.load_settings().cognito_configured


@pytest.mark.parametrize("secret", ["", "short"])
def test_cognito_without_a_strong_secret_fails_naming_it(monkeypatch, secret):
    _cognito(monkeypatch, secret)
    with pytest.raises(config.SettingsError, match="AUTH_JWT_SECRET"):
        config.load_settings()


@pytest.mark.parametrize("var", ["COGNITO_USER_POOL_ID", "COGNITO_APP_CLIENT_ID"])
def test_pool_without_client_or_the_reverse_fails(monkeypatch, var):
    _cognito(monkeypatch)
    # Blank rather than deleted: a deleted variable falls back to the developer's own .env, which holds the real
    # Cognito ids once deploy_auth.py has run, and the test would then pass or fail depending on that file.
    monkeypatch.setenv(var, "")
    with pytest.raises(config.SettingsError, match="COGNITO_APP_CLIENT_ID"):
        config.load_settings()


def test_bypass_needs_neither_cognito_nor_secret(monkeypatch):
    monkeypatch.setenv("LOCAL_AUTH_BYPASS", "true")
    assert config.load_settings().auth_bypass_enabled
