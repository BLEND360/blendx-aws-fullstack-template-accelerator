from dataclasses import replace

import pytest

from app.core.errors import ConflictError, NotFoundError
from app.core.models import MemoryRef, RuntimeValues, SessionConfig, SessionRecord
from app.repositories.in_memory_sessions import InMemorySessionStore

VALUES = RuntimeValues("model-a", ("t1",))


def record(session_id="s1", owner="alice", status="active", created="2026-10-08T10:00:00Z", revision=1):
    return SessionRecord(
        session_id=session_id,
        owner_id=owner,
        status=status,
        config=SessionConfig(VALUES, VALUES),
        memory=MemoryRef("s-" + "0" * 32, "u-" + "1" * 32),
        created_at=created,
        updated_at=created,
        revision=revision,
    )


@pytest.fixture
def store():
    return InMemorySessionStore()


def test_a_created_session_is_readable_by_its_owner(store):
    store.create(record())
    assert store.get("alice", "s1") == record()


def test_another_users_session_is_indistinguishable_from_a_missing_one(store):
    store.create(record())
    assert store.get("mallory", "s1") is None
    assert store.get("alice", "nope") is None


def test_list_returns_only_the_owners_active_sessions_newest_first(store):
    store.create(record("old", created="2026-10-01T00:00:00Z"))
    store.create(record("new", created="2026-10-08T00:00:00Z"))
    store.create(record("gone", status="deleting"))
    store.create(record("theirs", owner="bob"))
    assert [r.session_id for r in store.list("alice")] == ["new", "old"]


def test_a_deleting_session_is_hidden_unless_asked_for(store):
    store.create(record(status="deleting"))
    assert store.get("alice", "s1") is None
    assert store.get("alice", "s1", include_deleting=True).status == "deleting"


def test_update_bumps_the_revision(store):
    store.create(record())
    saved = store.update(replace(record(), updated_at="2026-10-09T00:00:00Z"), expected_revision=1)
    assert saved.revision == 2
    assert store.get("alice", "s1").updated_at == "2026-10-09T00:00:00Z"


def test_a_stale_revision_is_a_data_conflict_and_changes_nothing(store):
    store.create(record())
    store.update(replace(record(), updated_at="first"), expected_revision=1)  # the winner
    with pytest.raises(ConflictError) as raised:
        store.update(replace(record(), updated_at="second"), expected_revision=1)  # the loser
    assert raised.value.code == "data_conflict"
    assert store.get("alice", "s1").updated_at == "first"


def test_updating_a_missing_session_is_not_found(store):
    with pytest.raises(NotFoundError):
        store.update(record(), expected_revision=1)


def test_creating_the_same_id_twice_is_a_conflict(store):
    store.create(record())
    with pytest.raises(ConflictError):
        store.create(record())


def test_delete_removes_it_and_is_safe_to_repeat(store):
    store.create(record())
    store.delete("alice", "s1")
    store.delete("alice", "s1")
    assert store.get("alice", "s1", include_deleting=True) is None
