"""SessionService over the in-memory store and the fake memory."""

import itertools
import re

import pytest
from pydantic import BaseModel

from app.core.errors import ConflictError, NotFoundError, UnavailableError, ValidationFailedError
from app.harness.fake import FakeMemory
from app.repositories.in_memory_sessions import InMemorySessionStore
from app.services.runtime_config import Overrides
from app.services.sessions import SessionService
from app.tools.registry import Tool, ToolRegistry


class Empty(BaseModel):
    pass


def tool(tool_id):
    return Tool(tool_id, tool_id, "x", Empty, lambda a: {})


REGISTRY = ToolRegistry([tool("alpha"), tool("beta")])
ALLOWED = ["model-a", "model-b"]


class Env:
    def __init__(self):
        self.store, self.memory = InMemorySessionStore(), FakeMemory()
        ids = (f"{n:032x}" for n in itertools.count(1))
        clock = (f"2026-10-08T10:00:{n:02d}Z" for n in itertools.count())
        self.service = SessionService(
            self.store, self.memory, REGISTRY, allowed_model_ids=ALLOWED, now=lambda: next(clock), new_id=lambda: next(ids)
        )


@pytest.fixture
def env():
    return Env()


def test_creating_freezes_the_template_defaults_and_names_the_owner(env):
    record = env.service.create("alice", Overrides())
    assert record.owner_id == "alice" and record.status == "active" and record.revision == 1
    assert record.config.values.model_id == "model-a"
    assert record.config.values.tool_ids == ("alpha", "beta")
    assert record.config.frozen_defaults == record.config.values
    assert re.fullmatch(r"[0-9a-f]{32}", record.session_id)


def test_the_memory_coordinates_are_generated_on_the_server_and_fit_agentcores_patterns(env):
    a, b = env.service.create("alice", Overrides()), env.service.create("alice", Overrides())
    for record in (a, b):
        assert 33 <= len(record.memory.runtime_session_id) <= 100
        assert re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", record.memory.runtime_session_id)
    assert a.memory.runtime_session_id != b.memory.runtime_session_id
    assert a.memory.actor_id == b.memory.actor_id  # one actor per user
    assert a.memory.actor_id != env.service.create("bob", Overrides()).memory.actor_id
    assert "alice" not in a.memory.actor_id  # derived, not the raw identity


def test_overrides_at_creation_are_validated(env):
    assert env.service.create("alice", Overrides(model_id="model-b", tool_ids=["beta"])).config.values.model_id == "model-b"
    with pytest.raises(ValidationFailedError):
        env.service.create("alice", Overrides(model_id="not-allowed"))
    with pytest.raises(ValidationFailedError):
        env.service.create("alice", Overrides(tool_ids=["ghost"]))
    assert len(env.service.list("alice")) == 1  # only the valid one: a rejected creation leaves nothing behind


def test_list_returns_only_the_callers_sessions(env):
    mine = env.service.create("alice", Overrides())
    env.service.create("bob", Overrides())
    assert [r.session_id for r in env.service.list("alice")] == [mine.session_id]


def test_a_missing_session_and_someone_elses_look_exactly_alike(env):
    theirs = env.service.create("bob", Overrides())
    with pytest.raises(NotFoundError) as missing:
        env.service.get("alice", "0" * 32)
    with pytest.raises(NotFoundError) as foreign:
        env.service.get("alice", theirs.session_id)
    assert missing.value.to_payload() == foreign.value.to_payload()


def test_update_keeps_what_is_omitted_and_null_restores_the_frozen_default(env):
    record = env.service.create("alice", Overrides(model_id="model-b", tool_ids=["beta"]))
    changed = env.service.update("alice", record.session_id, Overrides(model_id="model-a"))
    assert (changed.config.values.model_id, changed.config.values.tool_ids) == ("model-a", ("beta",))
    restored = env.service.update("alice", record.session_id, Overrides(tool_ids=None))
    assert restored.config.values.tool_ids == ("alpha", "beta")
    assert restored.revision == 3


def test_updating_someone_elses_session_is_not_found(env):
    theirs = env.service.create("bob", Overrides())
    with pytest.raises(NotFoundError):
        env.service.update("alice", theirs.session_id, Overrides(model_id="model-b"))


def test_a_stale_read_in_update_surfaces_as_data_conflict(env, monkeypatch):
    record = env.service.create("alice", Overrides())
    stale = env.service.get("alice", record.session_id)
    env.service.update("alice", record.session_id, Overrides(model_id="model-b"))  # the winner
    monkeypatch.setattr(env.service, "get", lambda o, s: stale)  # the loser still holds revision 1
    with pytest.raises(ConflictError):
        env.service.update("alice", record.session_id, Overrides(model_id="model-a"))
    assert env.service.list("alice")[0].config.values.model_id == "model-b"


# --- deleting -----------------------------------------------------------------------
def test_delete_empties_the_memory_then_removes_the_metadata(env):
    record = env.service.create("alice", Overrides())
    env.memory.add(record.memory, "USER", "hi", "2026-10-08T10:00:00Z")
    env.service.delete("alice", record.session_id)
    assert env.memory.events == {}
    assert env.store.get("alice", record.session_id, include_deleting=True) is None


def test_a_failed_purge_leaves_the_session_hidden_and_a_retry_finishes_it(env):
    record = env.service.create("alice", Overrides())
    for i in range(4):
        env.memory.add(record.memory, "USER", f"m{i}", f"2026-10-08T10:00:0{i}Z")
    env.memory.purge_error = UnavailableError("History is unavailable.", dependency="memory")

    with pytest.raises(UnavailableError) as raised:
        env.service.delete("alice", record.session_id)
    assert (raised.value.code, raised.value.retryable) == ("memory_unavailable", True)
    assert env.service.list("alice") == []  # hidden from the list
    with pytest.raises(NotFoundError):
        env.service.get("alice", record.session_id)  # and from reads
    assert env.store.get("alice", record.session_id, include_deleting=True).status == "deleting"

    env.memory.purge_error = None  # the user retries
    env.service.delete("alice", record.session_id)
    assert env.memory.events.get(record.memory.runtime_session_id) is None
    assert env.store.get("alice", record.session_id, include_deleting=True) is None


def test_deleting_a_missing_or_foreign_session_is_not_found_and_touches_no_memory(env):
    theirs = env.service.create("bob", Overrides())
    with pytest.raises(NotFoundError):
        env.service.delete("alice", theirs.session_id)
    with pytest.raises(NotFoundError):
        env.service.delete("alice", "0" * 32)
    assert env.memory.purge_calls == 0
