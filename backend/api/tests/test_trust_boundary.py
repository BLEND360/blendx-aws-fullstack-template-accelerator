"""R7: what a client may send is a closed list, and what leaves never names a resource.

Read from the app's own OpenAPI document, so adding a field to a request or response
model that crosses the boundary fails here whoever adds it.
"""

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import dependencies as deps
from tests.api_stack import install, uninstall

# The only things a client may send: text, and a choice of model and tools.
CLIENT_MAY_SEND = {"text", "modelId", "toolIds"}
# Words that identify a resource or a person's data: never in a request field or a response field.
RESOURCE_WORDS = re.compile(r"arn|memory|actor|owner|skill|runtime|qualifier|endpoint|revision|harness|credential", re.I)


def schema_of(spec: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    return spec["components"]["schemas"][ref.rsplit("/", 1)[-1]] if ref else node


def property_names(spec: dict[str, Any], node: dict[str, Any], seen: frozenset[str] = frozenset()) -> set[str]:
    """Every property name reachable from a schema, through refs, arrays and unions."""
    ref = node.get("$ref")
    if ref in seen:
        return set()
    node_seen = seen | ({ref} if ref else set())
    node = schema_of(spec, node)
    names = set(node.get("properties", {}))
    for child in list(node.get("properties", {}).values()) + [node.get("items", {})] + node.get("anyOf", []) + node.get("allOf", []):
        names |= property_names(spec, child, node_seen) if child else set()
    return names


def session_operations(spec):
    for path, methods in spec["paths"].items():
        if path.startswith("/api/v1/sessions"):
            for method, operation in methods.items():
                yield f"{method.upper()} {path}", operation


def test_the_requests_the_api_accepts_carry_only_the_closed_list_of_client_fields():
    spec = app.openapi()
    sent = {}
    for name, operation in session_operations(spec):
        body = operation.get("requestBody")
        if body:
            sent[name] = property_names(spec, body["content"]["application/json"]["schema"])
    assert sent, "no request bodies found: is the OpenAPI document being read?"
    for operation, names in sent.items():
        assert names <= CLIENT_MAY_SEND, f"{operation} accepts {sorted(names - CLIENT_MAY_SEND)}"


def test_no_response_field_names_a_resource_an_owner_or_a_revision():
    spec = app.openapi()
    offenders = {}
    for name, operation in session_operations(spec):
        for status, response in operation.get("responses", {}).items():
            schema = response.get("content", {}).get("application/json", {}).get("schema")
            if schema:
                bad = {p for p in property_names(spec, schema) if RESOURCE_WORDS.search(p)}
                if bad:
                    offenders[f"{name} {status}"] = bad
    assert offenders == {}


def test_the_event_stream_payloads_name_no_resource_either():
    from dataclasses import fields

    from app.core.models import TURN_EVENT_NAMES

    names = {f.name for event_type in TURN_EVENT_NAMES for f in fields(event_type)}
    assert not {n for n in names if RESOURCE_WORDS.search(n)}


# --- the owner is the signed-in user, over HTTP ---------------------------------------------
@pytest.fixture
def stack():
    yield install()
    uninstall()


def test_each_user_sees_only_their_own_sessions_whatever_the_body_says(stack):
    client = TestClient(app, raise_server_exceptions=False)
    stack.as_user("alice")
    mine = client.post("/api/v1/sessions", json={"ownerId": "bob", "owner_id": "bob"}).json()["id"]

    stack.as_user("bob")
    assert client.get("/api/v1/sessions").json() == {"sessions": []}
    assert client.get(f"/api/v1/sessions/{mine}").status_code == 404
    assert client.delete(f"/api/v1/sessions/{mine}").status_code == 404
    assert client.patch(f"/api/v1/sessions/{mine}", json={"modelId": "model-b", "ownerId": "bob"}).status_code == 404

    stack.as_user("alice")
    assert client.get(f"/api/v1/sessions/{mine}").status_code == 200


def test_a_request_without_an_identity_never_reaches_a_service(stack):
    app.dependency_overrides.pop(deps.current_user)
    called = []
    app.dependency_overrides[deps.session_service] = lambda: called.append("session_service")  # would fail if used
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/sessions").status_code == 401
    assert client.post("/api/v1/sessions", json={}).status_code == 401
    assert called == []  # authentication is resolved before any service is built or called
