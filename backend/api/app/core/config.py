"""Typed settings, validated at import.

A missing or invalid variable stops the process at startup with the variable
named, instead of surfacing as a 500 on the first request that needs it.
Locally the values come from .env, written by scripts/setup.py from
project.toml; deployed, the app stack sets them on the ECS task.
"""

import os

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsError(RuntimeError):
    pass


class Settings(BaseSettings):
    project_name: str
    aws_region: str
    sessions_table_name: str
    items_table_name: str
    # Empty until the starter harness is deployed: /ready reports it as
    # misconfigured rather than the app refusing to start.
    harness_arn: str = ""
    harness_endpoint: str
    allowed_model_ids: list[str]  # JSON list, e.g. ["model-a"]
    cors_origins: str  # comma-separated exact origins

    # Local-only: serve authenticated endpoints as a stand-in user. Ignored in
    # a deployed task (see auth_bypass_enabled), so a stray value in a task
    # definition cannot open production.
    local_auth_bypass: bool = False
    local_auth_user_id: str = "local-dev-user"
    local_auth_user_email: str = "local-dev@example.com"
    local_auth_user_name: str = "Local Dev"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("allowed_model_ids")
    @classmethod
    def _models_not_empty(cls, value: list[str]) -> list[str]:
        if not [m for m in value if m.strip()]:
            raise ValueError("must list at least one model id")
        return value

    @field_validator("cors_origins")
    @classmethod
    def _cors_exact_origins(cls, value: str) -> str:
        # Browsers reject `*` on credentialed requests, so a wildcard would look
        # configured while every cross-origin call failed. Fail here instead.
        origins = [o.strip() for o in value.split(",") if o.strip()]
        if not origins:
            raise ValueError("is empty: the SPA would be blocked by the browser")
        if "*" in origins:
            raise ValueError("contains '*'; set the exact SPA origin(s)")
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def running_on_ecs(self) -> bool:
        """The ECS agent injects the metadata endpoint into every task; config cannot fake it away."""
        return bool(
            os.getenv("ECS_CONTAINER_METADATA_URI_V4")
            or os.getenv("ECS_CONTAINER_METADATA_URI")
            or os.getenv("AWS_EXECUTION_ENV")
        )

    @property
    def auth_bypass_enabled(self) -> bool:
        return self.local_auth_bypass and not self.running_on_ecs


def load_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        problems = "; ".join(
            f"{str(err['loc'][0]).upper()}: {err['msg']}" for err in exc.errors()
        )
        raise SettingsError(f"Invalid configuration: {problems}") from None


settings = load_settings()
