from dataclasses import replace

import pytest

from app.core.errors import NotFoundError
from app.harness.fake import FakeMemory
from app.repositories.in_memory_sessions import InMemorySessionStore
from app.services.history import HistoryMessage, HistoryService
from tests.test_sessions import REGISTRY, ALLOWED
from app.services.runtime_config import Overrides
from app.services.sessions import SessionService


class Env:
    def __init__(self):
        self.store, self.memory = InMemorySessionStore(), FakeMemory()
        self.sessions = SessionService(self.store, self.memory, REGISTRY, allowed_model_ids=ALLOWED)
        self.history = HistoryService(self.store, self.memory)


@pytest.fixture
def env():
    return Env()


def test_messages_come_back_in_chronological_order_as_user_and_assistant(env):
    record = env.sessions.create("alice", Overrides())
    env.memory.add(record.memory, "ASSISTANT", "second", "2026-10-08T10:00:02Z", "2#b")
    env.memory.add(record.memory, "USER", "first", "2026-10-08T10:00:01Z", "1#a")
    env.memory.add(record.memory, "USER", "third", "2026-10-08T10:00:03Z", "3#c")
    assert env.history.get("alice", record.session_id) == [
        HistoryMessage("user", "first", "2026-10-08T10:00:01Z"),
        HistoryMessage("assistant", "second", "2026-10-08T10:00:02Z"),
        HistoryMessage("user", "third", "2026-10-08T10:00:03Z"),
    ]


def test_events_with_the_same_timestamp_are_ordered_by_their_sequence_number(env):
    record = env.sessions.create("alice", Overrides())
    same = "2026-10-08T10:00:00Z"
    env.memory.add(record.memory, "USER", "ten", same, "10#a")
    env.memory.add(record.memory, "USER", "nine", same, "9#a")
    assert [m.text for m in env.history.get("alice", record.session_id)] == ["nine", "ten"]


def test_only_conversation_is_returned(env):
    record = env.sessions.create("alice", Overrides())
    env.memory.add(record.memory, "USER", "hi", "2026-10-08T10:00:01Z")
    env.memory.add(record.memory, "TOOL", "tool output", "2026-10-08T10:00:02Z")
    env.memory.add(record.memory, "OTHER", None, "2026-10-08T10:00:03Z")
    env.memory.add(record.memory, "ASSISTANT", "", "2026-10-08T10:00:04Z")
    assert [m.text for m in env.history.get("alice", record.session_id)] == ["hi"]


def test_a_session_with_no_events_has_an_empty_history(env):
    record = env.sessions.create("alice", Overrides())
    assert env.history.get("alice", record.session_id) == []


def test_ownership_is_checked_before_the_memory_is_read(env):
    theirs = env.sessions.create("bob", Overrides())
    env.memory.add(theirs.memory, "USER", "bob's secret", "2026-10-08T10:00:01Z")
    with pytest.raises(NotFoundError):
        env.history.get("alice", theirs.session_id)
    with pytest.raises(NotFoundError):
        env.history.get("alice", "0" * 32)
    assert env.memory.list_calls == 0


def test_a_session_being_deleted_has_no_history(env):
    record = env.sessions.create("alice", Overrides())
    env.store.update(replace(record, status="deleting"), expected_revision=record.revision)
    with pytest.raises(NotFoundError):
        env.history.get("alice", record.session_id)
    assert env.memory.list_calls == 0


def test_history_keeps_no_copy_of_the_conversation(env):
    record = env.sessions.create("alice", Overrides())
    env.memory.add(record.memory, "USER", "remember me not", "2026-10-08T10:00:01Z")
    env.history.get("alice", record.session_id)
    assert "remember me not" not in repr(env.store.get("alice", record.session_id))
