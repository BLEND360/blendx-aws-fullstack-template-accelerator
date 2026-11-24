"""One contract, two implementations: the in-process stores and the DynamoDB adapters (under moto)
must behave identically, so a service tested against one is correct against the other."""

from dataclasses import replace

import pytest

from app.core.errors import ConflictError, NotFoundError
from app.core.models import ItemRecord, MemoryRef, RuntimeValues, SessionConfig, SessionRecord
from app.repositories.dynamo import DynamoItemStore, DynamoSessionStore
from app.repositories.in_memory_items import InMemoryItemStore
from app.repositories.in_memory_sessions import InMemorySessionStore

VALUES = RuntimeValues("model-a", ("t1",))


def session(session_id="s1", owner="alice", status="active", created="2026-10-08T10:00:00Z", revision=1):
    return SessionRecord(
        session_id=session_id,
        owner_id=owner,
        status=status,
        config=SessionConfig(VALUES, RuntimeValues("model-b", ())),
        memory=MemoryRef("s-" + "0" * 32, "u-" + "1" * 32),
        created_at=created,
        updated_at=created,
        revision=revision,
    )


def item(item_id="i1", owner="alice", name="First", description="about it", created="2026-10-08T10:00:00Z"):
    return ItemRecord(item_id, owner, name, description, created_at=created, updated_at=created, revision=1)


@pytest.fixture(params=["memory", "dynamodb"])
def sessions(request):
    if request.param == "memory":
        return InMemorySessionStore()
    return DynamoSessionStore(request.getfixturevalue("dynamo").Table("test-sessions"))


@pytest.fixture(params=["memory", "dynamodb"])
def items(request):
    if request.param == "memory":
        return InMemoryItemStore()
    return DynamoItemStore(request.getfixturevalue("dynamo").Table("test-items"))


# --- sessions ---------------------------------------------------------------------------
def test_a_created_session_is_readable_by_its_owner_and_round_trips_exactly(sessions):
    sessions.create(session())
    assert sessions.get("alice", "s1") == session()


def test_another_users_session_is_indistinguishable_from_a_missing_one(sessions):
    sessions.create(session())
    assert sessions.get("mallory", "s1") is None
    assert sessions.get("alice", "nope") is None


def test_list_returns_only_the_owners_active_sessions_newest_first(sessions):
    sessions.create(session("old", created="2026-10-01T00:00:00Z"))
    sessions.create(session("new", created="2026-10-08T00:00:00Z"))
    sessions.create(session("gone", status="deleting"))
    sessions.create(session("theirs", owner="bob"))
    assert [r.session_id for r in sessions.list("alice")] == ["new", "old"]


def test_a_deleting_session_is_hidden_unless_asked_for(sessions):
    sessions.create(session(status="deleting"))
    assert sessions.get("alice", "s1") is None
    assert sessions.get("alice", "s1", include_deleting=True).status == "deleting"


def test_session_update_bumps_the_revision(sessions):
    sessions.create(session())
    saved = sessions.update(replace(session(), updated_at="2026-10-09T00:00:00Z"), expected_revision=1)
    assert saved.revision == 2
    assert sessions.get("alice", "s1").updated_at == "2026-10-09T00:00:00Z"


def test_a_stale_session_revision_is_a_data_conflict_and_changes_nothing(sessions):
    sessions.create(session())
    sessions.update(replace(session(), updated_at="first"), expected_revision=1)  # the winner
    with pytest.raises(ConflictError) as raised:
        sessions.update(replace(session(), updated_at="second"), expected_revision=1)  # the loser
    assert raised.value.code == "data_conflict"
    assert sessions.get("alice", "s1").updated_at == "first"


def test_updating_a_missing_session_is_not_found(sessions):
    with pytest.raises(NotFoundError):
        sessions.update(session(), expected_revision=1)


def test_one_user_cannot_update_anothers_session_even_with_the_right_id_and_revision(sessions):
    sessions.create(session())
    with pytest.raises(NotFoundError):
        sessions.update(replace(session(), owner_id="mallory", updated_at="stolen"), expected_revision=1)
    assert sessions.get("alice", "s1").updated_at != "stolen"


def test_creating_the_same_session_id_twice_is_a_conflict(sessions):
    sessions.create(session())
    with pytest.raises(ConflictError):
        sessions.create(session())


def test_the_same_session_id_can_exist_for_two_owners(sessions):
    sessions.create(session(owner="alice"))
    sessions.create(session(owner="bob"))
    assert sessions.get("alice", "s1").owner_id == "alice"
    assert sessions.get("bob", "s1").owner_id == "bob"


def test_session_delete_removes_it_and_is_safe_to_repeat(sessions):
    sessions.create(session())
    sessions.delete("alice", "s1")
    sessions.delete("alice", "s1")
    assert sessions.get("alice", "s1", include_deleting=True) is None


# --- items ------------------------------------------------------------------------------
def test_a_created_item_round_trips_exactly(items):
    items.create(item())
    assert items.get("alice", "i1") == item()


def test_an_item_without_a_description_round_trips(items):
    items.create(item(description=None))
    assert items.get("alice", "i1").description is None


def test_another_users_item_is_indistinguishable_from_a_missing_one(items):
    items.create(item())
    assert items.get("mallory", "i1") is None
    assert items.get("alice", "nope") is None


def test_item_list_is_the_owners_only_newest_first(items):
    items.create(item("old", created="2026-10-01T00:00:00Z"))
    items.create(item("new", created="2026-10-08T00:00:00Z"))
    items.create(item("theirs", owner="bob"))
    assert [r.item_id for r in items.list("alice")] == ["new", "old"]
    assert items.list("nobody") == []


def test_item_update_bumps_the_revision_and_a_stale_one_conflicts(items):
    items.create(item())
    assert items.update(replace(item(), name="Renamed"), expected_revision=1).revision == 2
    with pytest.raises(ConflictError) as raised:
        items.update(replace(item(), name="Late"), expected_revision=1)
    assert raised.value.code == "data_conflict"
    assert items.get("alice", "i1").name == "Renamed"


def test_updating_a_missing_or_foreign_item_is_not_found(items):
    with pytest.raises(NotFoundError):
        items.update(item(), expected_revision=1)
    items.create(item())
    with pytest.raises(NotFoundError):
        items.update(replace(item(), owner_id="mallory"), expected_revision=1)


def test_item_delete_is_safe_to_repeat_and_only_touches_the_owners_row(items):
    items.create(item(owner="alice"))
    items.create(item(owner="bob"))
    items.delete("alice", "i1")
    items.delete("alice", "i1")
    assert items.get("alice", "i1") is None
    assert items.get("bob", "i1") is not None
