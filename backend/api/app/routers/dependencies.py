"""Request dependencies shared by routers."""

from dataclasses import dataclass
from functools import cache

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.errors import InvalidTokenError
from app.core.logging import get_logger
from app.harness.client import AgentCoreHarness, BotoInvoker, RawInvoker
from app.harness.fake import FakeMemory
from app.harness.memory import AgentCoreMemory
from app.harness.replay import ReplayHarness
from app.repositories.in_memory_sessions import InMemorySessionStore
from app.services.history import HistoryService
from app.services.ports import HarnessPort, MemoryPort, SessionStore, ToolPort
from app.services.sessions import SessionService
from app.services.turn import TurnService
from app.tools import builtin

logger = get_logger(__name__)
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    """The caller. Every authenticated route depends on this.

    Token validation (Cognito id token in, app JWT out) arrives with ST-08;
    until then only the local bypass admits anyone. The bypass is ignored in a
    deployed task, whatever LOCAL_AUTH_BYPASS says.
    """
    if settings.auth_bypass_enabled:
        logger.warning("local_auth_bypass_used", user_id=settings.local_auth_user_id)
        return User(settings.local_auth_user_id, settings.local_auth_user_email, settings.local_auth_user_name)
    raise InvalidTokenError(detail="no token validation configured" if credentials else "missing bearer token")


# --- Wiring -----------------------------------------------------------------------
# The one place adapters are chosen. Each factory is a FastAPI dependency, so a test
# replaces it with `app.dependency_overrides[factory] = ...` and needs no AWS.
@cache
def session_store() -> SessionStore:
    return InMemorySessionStore()  # ST-05 replaces this with the DynamoDB repository


@cache
def replay_memory() -> FakeMemory:
    """Demonstration mode: the conversation lives here, shared by the replay harness (which writes it) and history (which reads it)."""
    return FakeMemory()


@cache
def harness_memory() -> MemoryPort:
    return replay_memory() if settings.replay_enabled else AgentCoreMemory(settings.harness_arn)


@cache
def tool_registry() -> ToolPort:
    return builtin.registry


@cache
def session_service() -> SessionService:
    return SessionService(
        session_store(), harness_memory(), tool_registry(), allowed_model_ids=settings.allowed_model_ids
    )


@cache
def history_service() -> HistoryService:
    return HistoryService(session_store(), harness_memory())


@cache
def raw_invoker() -> RawInvoker:
    return BotoInvoker(idle_timeout_seconds=settings.harness_idle_timeout_seconds)


@cache
def harness() -> HarnessPort:
    if settings.replay_enabled:
        return ReplayHarness(replay_memory(), event_delay_seconds=settings.harness_replay_delay_seconds)
    # Both values come from configuration and nowhere else: pointing the app at another harness is a config change.
    return AgentCoreHarness(
        raw_invoker(),
        harness_arn=settings.harness_arn,
        endpoint=settings.harness_endpoint,
        turn_timeout_seconds=settings.harness_turn_timeout_seconds,
    )


@cache
def turn_service() -> TurnService:
    return TurnService(
        session_store(),
        harness(),
        tool_registry(),
        # Replay needs no harness, so an empty ARN is not "unconfigured" there.
        harness_arn="replay" if settings.replay_enabled else settings.harness_arn,
        max_tool_rounds=settings.max_tool_rounds,
    )
