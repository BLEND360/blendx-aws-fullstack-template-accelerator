import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.in_memory_items import InMemoryItemStore
from app.routers import dependencies as deps
from app.services.items import ItemService
from tests.api_stack import uninstall

PATH = "/api/v1/items"


def as_user(user_id: str) -> None:
    app.dependency_overrides[deps.current_user] = lambda: deps.User(user_id, f"{user_id}@example.test", user_id.title())


@pytest.fixture
def client():
    store = InMemoryItemStore()
    app.dependency_overrides[deps.item_service] = lambda: ItemService(store)
    as_user("alice")
    yield TestClient(app)
    uninstall()


def test_create_then_list_returns_the_shape_the_spa_expects(client):
    created = client.post(PATH, json={"name": "  Laptop ", "description": "work"})
    assert created.status_code == 201
    body = created.json()
    assert set(body) == {"id", "name", "description", "createdAt", "updatedAt"}  # no owner, no revision
    assert body["name"] == "Laptop"
    assert client.get(PATH).json() == {"items": [body]}


def test_the_owner_comes_from_the_identity_never_from_the_body(client):
    created = client.post(PATH, json={"name": "Mine", "ownerId": "bob", "owner_id": "bob"}).json()
    as_user("bob")
    assert client.get(PATH).json() == {"items": []}
    assert client.get(f"{PATH}/{created['id']}").status_code == 404


def test_a_missing_item_and_someone_elses_are_the_same_404(client):
    mine = client.post(PATH, json={"name": "Mine"}).json()["id"]
    as_user("mallory")
    foreign = client.get(f"{PATH}/{mine}")
    missing = client.get(f"{PATH}/nope")
    assert foreign.status_code == missing.status_code == 404
    strip = lambda r: {k: v for k, v in r.json()["error"].items() if k != "requestId"}  # noqa: E731
    assert strip(foreign) == strip(missing)
    for call in (
        lambda: client.patch(f"{PATH}/{mine}", json={"name": "stolen"}),
        lambda: client.delete(f"{PATH}/{mine}"),
    ):
        assert call().status_code == 404
    as_user("alice")
    assert client.get(f"{PATH}/{mine}").json()["name"] == "Mine"  # untouched


def test_patch_changes_only_what_was_sent_and_null_clears_the_description(client):
    item = client.post(PATH, json={"name": "Old", "description": "text"}).json()
    renamed = client.patch(f"{PATH}/{item['id']}", json={"name": "New"}).json()
    assert (renamed["name"], renamed["description"]) == ("New", "text")
    cleared = client.patch(f"{PATH}/{item['id']}", json={"description": None}).json()
    assert (cleared["name"], cleared["description"]) == ("New", None)


def test_a_null_name_is_rejected(client):
    item = client.post(PATH, json={"name": "Old"}).json()
    response = client.patch(f"{PATH}/{item['id']}", json={"name": None})
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "   "}, {"name": "x" * 121}, {"name": "ok", "description": "d" * 2001}])
def test_invalid_input_is_a_422(client, body):
    assert client.post(PATH, json=body).status_code == 422


def test_delete_removes_it(client):
    item = client.post(PATH, json={"name": "Gone"}).json()["id"]
    assert client.delete(f"{PATH}/{item}").status_code == 204
    assert client.get(f"{PATH}/{item}").status_code == 404
    assert client.delete(f"{PATH}/{item}").status_code == 404


def test_every_route_requires_a_signed_in_user(client):
    app.dependency_overrides.pop(deps.current_user)
    for method in ("get", "post", "patch", "delete"):
        path = PATH if method in ("get", "post") else f"{PATH}/x"
        kwargs = {"json": {"name": "n"}} if method in ("post", "patch") else {}
        assert getattr(client, method)(path, **kwargs).status_code == 401, method


def test_the_dynamodb_wiring_serves_the_same_api(dynamo):
    from app.repositories.dynamo import DynamoItemStore

    app.dependency_overrides[deps.item_service] = lambda: ItemService(DynamoItemStore(dynamo.Table("test-items")))
    as_user("alice")
    try:
        client = TestClient(app)
        created = client.post(PATH, json={"name": "Persisted"}).json()
        assert client.get(PATH).json() == {"items": [created]}
        as_user("bob")
        assert client.get(PATH).json() == {"items": []}
    finally:
        uninstall()
