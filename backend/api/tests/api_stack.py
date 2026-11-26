"""Shared setup for the API tests: the app with every adapter replaced by an in-process stand-in.

Not a conftest.py on purpose: only the sessions and turns API tests want the
overrides, and the older tests rely on the app exactly as wired.
"""

from dataclasses import dataclass
from typing import Any

from app.harness.client import AgentCoreHarness
from app.harness.fake import FakeMemory, ReplayInvoker
from app.main import app
from app.repositories.in_memory_sessions import InMemorySessionStore
from app.routers import dependencies as deps
from app.services.history import HistoryService
from app.services.sessions import SessionService
from app.services.turn import TurnService
from app.tools import builtin

ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-1234567890"


@dataclass
class Stack:
    store: InMemorySessionStore
    memory: FakeMemory
    sessions: SessionService
    history: HistoryService
    invoker: ReplayInvoker | None = None

    def as_user(self, user_id: str) -> None:
        app.dependency_overrides[deps.current_user] = lambda: deps.User(user_id, f"{user_id}@example.test", user_id.title())


def install(invoker: ReplayInvoker | None = None, *, models=("model-a", "model-b"), harness_arn: str = ARN) -> Stack:
    """Replace the wiring with in-memory adapters and the replay harness; returns the pieces to poke at."""
    store, memory = InMemorySessionStore(), FakeMemory()
    sessions = SessionService(store, memory, builtin.registry, allowed_model_ids=list(models))
    history = HistoryService(store, memory)
    app.dependency_overrides[deps.session_store] = lambda: store
    app.dependency_overrides[deps.harness_memory] = lambda: memory
    app.dependency_overrides[deps.session_service] = lambda: sessions
    app.dependency_overrides[deps.history_service] = lambda: history
    app.dependency_overrides[deps.current_user] = lambda: deps.User("alice", "alice@example.test", "Alice")
    if invoker is not None:
        harness = AgentCoreHarness(invoker, harness_arn=ARN, endpoint="PROD", turn_timeout_seconds=900)
        turns = TurnService(store, harness, builtin.registry, harness_arn=harness_arn, max_tool_rounds=8)
        app.dependency_overrides[deps.turn_service] = lambda: turns
    return Stack(store, memory, sessions, history, invoker)


def uninstall() -> None:
    app.dependency_overrides.clear()


def walk_strings(value: Any):
    """Every string in a JSON document, keys and values: for 'this never appears anywhere' checks."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from walk_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk_strings(v)
    elif isinstance(value, str):
        yield value
