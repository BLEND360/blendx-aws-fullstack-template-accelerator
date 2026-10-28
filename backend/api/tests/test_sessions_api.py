"""The sessions API, over HTTP, with every adapter replaced by an in-process stand-in."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.core.context import REQUEST_ID_HEADER
from app.core.errors import ConflictError, UnavailableError
from app.main import app
from app.routers import dependencies as deps
from tests.api_stack import install, uninstall, walk_strings


@pytest.fixture
def stack():
    yield install()
    uninstall()


@pytest.fixture
def client(stack):
    return TestClient(app, raise_server_exceptions=False)


def create(client, **body):
    response = client.post("/api/v1/sessions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_creating_returns_the_resolved_configuration_in_display_form(client):
    session = create(client)
    assert set(session) == {"id", "createdAt", "updatedAt", "config"}
    assert session["config"] == {
        "modelId": "model-a",
        "toolIds": ["current_time"],
        "tools": [{"id": "current_time", "label": "Checking the time"}],
    }


def test_creating_with_overrides_applies_them(client):
    config = create(client, modelId="model-b", toolIds=[])["config"]
    assert (config["modelId"], config["toolIds"], config["tools"]) == ("model-b", [], [])


def test_an_override_outside_whats_allowed_is_a_validation_error_with_its_field(client):
    bad_model = client.post("/api/v1/sessions", json={"modelId": "nope"})
    assert bad_model.status_code == 422
    assert bad_model.json()["error"]["code"] == "validation_error"
    assert bad_model.json()["error"]["fields"] == [{"location": "body.modelId", "message": "Model is not allowed."}]
    bad_tool = client.post("/api/v1/sessions", json={"toolIds": ["ghost"]})
    assert bad_tool.json()["error"]["fields"][0]["location"] == "body.toolIds.0"
    wrong_type = client.post("/api/v1/sessions", json={"modelId": 5})
    assert wrong_type.status_code == 422 and wrong_type.json()["error"]["code"] == "validation_error"


def test_list_get_update_delete(client):
    first, second = create(client), create(client, modelId="model-b")
    listed = client.get("/api/v1/sessions").json()["sessions"]
    assert {s["id"] for s in listed} == {first["id"], second["id"]}
    assert client.get(f"/api/v1/sessions/{first['id']}").json() == first

    patched = client.patch(f"/api/v1/sessions/{first['id']}", json={"modelId": "model-b"})
    assert patched.status_code == 200 and patched.json()["config"]["modelId"] == "model-b"

    assert client.delete(f"/api/v1/sessions/{first['id']}").status_code == 204
    assert client.get(f"/api/v1/sessions/{first['id']}").status_code == 404
    assert [s["id"] for s in client.get("/api/v1/sessions").json()["sessions"]] == [second["id"]]


def test_patch_distinguishes_a_field_left_out_from_an_explicit_null(client):
    session = create(client, modelId="model-b", toolIds=[])
    sid = session["id"]
    kept = client.patch(f"/api/v1/sessions/{sid}", json={}).json()["config"]
    assert (kept["modelId"], kept["toolIds"]) == ("model-b", [])
    restored = client.patch(f"/api/v1/sessions/{sid}", json={"modelId": None}).json()["config"]
    assert (restored["modelId"], restored["toolIds"]) == ("model-a", [])  # only the model went back to its default
    both = client.patch(f"/api/v1/sessions/{sid}", json={"modelId": None, "toolIds": None}).json()["config"]
    assert both["toolIds"] == ["current_time"]


def test_a_missing_session_and_someone_elses_get_the_same_404_body(client, stack):
    stack.as_user("bob")
    theirs = create(client)
    stack.as_user("alice")
    headers = {REQUEST_ID_HEADER: "rid-same"}
    foreign = client.get(f"/api/v1/sessions/{theirs['id']}", headers=headers)
    missing = client.get(f"/api/v1/sessions/{'0' * 32}", headers=headers)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    for method, path in [("patch", ""), ("delete", ""), ("get", "/messages")]:
        r = getattr(client, method)(f"/api/v1/sessions/{theirs['id']}{path}", **({"json": {}} if method == "patch" else {}))
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_a_client_cannot_name_the_harness_the_memory_the_actor_or_the_owner(client, stack):
    smuggled = {
        "modelId": "model-b",
        "harnessArn": "arn:aws:bedrock-agentcore:us-east-1:1:harness/evil-1234567890",
        "memoryId": "evil-memory",
        "actorId": "evil-actor",
        "runtimeSessionId": "s-" + "e" * 40,
        "ownerId": "bob",
        "owner_id": "bob",
        "skills": [{"path": "evil"}],
    }
    session = create(client, **smuggled)
    record = stack.store.get("alice", session["id"])
    assert record.owner_id == "alice"  # from the identity, never the body
    assert record.memory.runtime_session_id != smuggled["runtimeSessionId"]
    assert record.memory.actor_id != "evil-actor"
    assert stack.store.get("bob", session["id"]) is None


def test_no_response_carries_memory_coordinates_revision_or_owner(client, stack):
    session = create(client)
    record = stack.store.get("alice", session["id"])
    stack.memory.add(record.memory, "USER", "hi", "2026-10-08T10:00:00Z")
    responses = [
        client.get("/api/v1/sessions").json(),
        client.get(f"/api/v1/sessions/{session['id']}").json(),
        client.patch(f"/api/v1/sessions/{session['id']}", json={"modelId": "model-b"}).json(),
        client.get(f"/api/v1/sessions/{session['id']}/messages").json(),
        session,
    ]
    seen = " ".join(s for r in responses for s in walk_strings(r))
    for secret in (record.memory.runtime_session_id, record.memory.actor_id, "revision", "owner", "memory"):
        assert secret not in seen


# --- deleting ------------------------------------------------------------------------
def test_delete_empties_the_memory(client, stack):
    session = create(client)
    record = stack.store.get("alice", session["id"])
    stack.memory.add(record.memory, "USER", "hi", "2026-10-08T10:00:00Z")
    assert client.delete(f"/api/v1/sessions/{session['id']}").status_code == 204
    assert stack.memory.events == {}


def test_a_memory_failure_leaves_the_session_hidden_and_the_retry_completes_the_delete(client, stack):
    session = create(client)
    stack.memory.purge_error = UnavailableError("History is temporarily unavailable.", dependency="memory")

    failed = client.delete(f"/api/v1/sessions/{session['id']}")
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "memory_unavailable" and failed.json()["error"]["retryable"] is True
    assert client.get("/api/v1/sessions").json() == {"sessions": []}
    assert client.get(f"/api/v1/sessions/{session['id']}").status_code == 404

    stack.memory.purge_error = None
    assert client.delete(f"/api/v1/sessions/{session['id']}").status_code == 204
    assert stack.store.get("alice", session["id"], include_deleting=True) is None


def test_a_losing_concurrent_update_is_a_409_data_conflict(client, stack, monkeypatch):
    session = create(client)

    def lose(record, expected_revision):
        raise ConflictError("This session changed since you loaded it. Reload and try again.", dependency="data")

    monkeypatch.setattr(stack.store, "update", lose)
    response = client.patch(f"/api/v1/sessions/{session['id']}", json={"modelId": "model-b"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "data_conflict"


# --- history -------------------------------------------------------------------------
def test_history_is_the_conversation_in_order(client, stack):
    session = create(client)
    record = stack.store.get("alice", session["id"])
    stack.memory.add(record.memory, "ASSISTANT", "hello", "2026-10-08T10:00:02Z", "2#b")
    stack.memory.add(record.memory, "USER", "hi", "2026-10-08T10:00:01Z", "1#a")
    assert client.get(f"/api/v1/sessions/{session['id']}/messages").json() == {
        "messages": [
            {"role": "user", "text": "hi", "createdAt": "2026-10-08T10:00:01Z"},
            {"role": "assistant", "text": "hello", "createdAt": "2026-10-08T10:00:02Z"},
        ]
    }
    assert stack.memory.list_calls == 1


def test_history_of_a_foreign_session_never_reads_the_memory(client, stack):
    stack.as_user("bob")
    theirs = create(client)
    stack.as_user("alice")
    assert client.get(f"/api/v1/sessions/{theirs['id']}/messages").status_code == 404
    assert stack.memory.list_calls == 0


# --- identity and startup -------------------------------------------------------------
def test_every_route_requires_a_signed_in_user(client):
    app.dependency_overrides.pop(deps.current_user)  # no bypass in the test environment: 401
    for method, path in [
        ("post", "/api/v1/sessions"), ("get", "/api/v1/sessions"), ("get", "/api/v1/sessions/x"),
        ("patch", "/api/v1/sessions/x"), ("delete", "/api/v1/sessions/x"), ("get", "/api/v1/sessions/x/messages"),
    ]:
        response = getattr(client, method)(path, **({"json": {}} if method in ("post", "patch") else {}))
        assert response.status_code == 401, (method, path)


def test_starting_the_app_warns_that_data_lives_in_memory(caplog):
    with caplog.at_level(logging.WARNING):
        with TestClient(app):
            pass
    assert any(r.getMessage() == "data_store_in_memory" for r in caplog.records)
