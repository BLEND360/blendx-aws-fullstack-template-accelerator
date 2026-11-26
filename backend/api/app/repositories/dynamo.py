"""DynamoDB adapters for the session and item ports.

Both tables are keyed owner_id + the entity's own id, so every read and write names its owner:
another user's row is absent by construction, not filtered out. Writes carry a `revision`
condition, which is what makes concurrent updates safe across ECS tasks (the in-memory stores
use a lock, which only works inside one process).

Reads are strongly consistent: a client that creates a row and lists straight after must see it.
Failures leave as AppError (`data_*`); botocore text never does.
"""

from typing import Any

from boto3.dynamodb.conditions import Key

from app.core.errors import DATA, ConflictError, NotFoundError, classify_aws_error
from app.core.models import ItemRecord, MemoryRef, RuntimeValues, SessionConfig, SessionRecord

OWNER = "owner_id"


class OwnedTable:
    """Conditional writes and owner-scoped reads on a table keyed (owner_id, <sort_key>)."""

    def __init__(self, table: Any, sort_key: str, noun: str) -> None:
        self._table, self._sk, self._noun = table, sort_key, noun

    def _call(self, operation: str, **kwargs: Any) -> Any:
        try:
            return getattr(self._table, operation)(**kwargs)
        except Exception as exc:
            raise classify_aws_error(exc, dependency=DATA) from exc

    def _changed(self, detail: str) -> ConflictError:
        return ConflictError(
            f"This {self._noun} changed since you loaded it. Reload and try again.", dependency=DATA, detail=detail
        )

    def _key(self, owner_id: str, sort_value: str) -> dict[str, str]:
        return {OWNER: owner_id, self._sk: sort_value}

    def create(self, item: dict[str, Any]) -> None:
        try:
            self._call(
                "put_item",
                Item=item,
                ConditionExpression="attribute_not_exists(#o)",
                ExpressionAttributeNames={"#o": OWNER},
            )
        except ConflictError as exc:
            raise self._changed("id already exists") from exc

    def get(self, owner_id: str, sort_value: str) -> dict[str, Any] | None:
        return self._call("get_item", Key=self._key(owner_id, sort_value), ConsistentRead=True).get("Item")

    def query(self, owner_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        start: dict[str, Any] = {}
        while True:
            page = self._call("query", KeyConditionExpression=Key(OWNER).eq(owner_id), ConsistentRead=True, **start)
            items += page["Items"]
            if "LastEvaluatedKey" not in page:
                return items
            start = {"ExclusiveStartKey": page["LastEvaluatedKey"]}

    def replace(self, item: dict[str, Any], expected_revision: int) -> dict[str, Any]:
        saved = {**item, "revision": expected_revision + 1}
        try:
            self._call(
                "put_item",
                Item=saved,
                # False when the row is gone as well as when it moved on: told apart below.
                ConditionExpression="#r = :expected",
                ExpressionAttributeNames={"#r": "revision"},
                ExpressionAttributeValues={":expected": expected_revision},
            )
        except ConflictError as exc:
            if self.get(item[OWNER], item[self._sk]) is None:
                raise NotFoundError(f"{self._noun.capitalize()} not found.") from exc
            raise self._changed(f"expected revision {expected_revision}") from exc
        return saved

    def delete(self, owner_id: str, sort_value: str) -> None:
        self._call("delete_item", Key=self._key(owner_id, sort_value))  # idempotent


def _values(v: RuntimeValues) -> dict[str, Any]:
    return {"model_id": v.model_id, "tool_ids": list(v.tool_ids)}


def _runtime(d: dict[str, Any]) -> RuntimeValues:
    return RuntimeValues(d["model_id"], tuple(d["tool_ids"]))


class DynamoSessionStore:
    """Session metadata only: owner, status, the frozen runtime config and the memory coordinates.
    The conversation itself lives in the harness's memory and is never written here."""

    def __init__(self, table: Any) -> None:
        self._rows = OwnedTable(table, "session_id", "session")

    @staticmethod
    def _to_item(r: SessionRecord) -> dict[str, Any]:
        return {
            OWNER: r.owner_id,
            "session_id": r.session_id,
            "status": r.status,
            "config": {"values": _values(r.config.values), "frozen_defaults": _values(r.config.frozen_defaults)},
            "memory": {"runtime_session_id": r.memory.runtime_session_id, "actor_id": r.memory.actor_id},
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "revision": r.revision,
        }

    @staticmethod
    def _from_item(i: dict[str, Any]) -> SessionRecord:
        return SessionRecord(
            session_id=i["session_id"],
            owner_id=i[OWNER],
            status=i["status"],
            config=SessionConfig(_runtime(i["config"]["values"]), _runtime(i["config"]["frozen_defaults"])),
            memory=MemoryRef(i["memory"]["runtime_session_id"], i["memory"]["actor_id"]),
            created_at=i["created_at"],
            updated_at=i["updated_at"],
            revision=int(i["revision"]),
        )

    def create(self, record: SessionRecord) -> None:
        self._rows.create(self._to_item(record))

    def get(self, owner_id: str, session_id: str, *, include_deleting: bool = False) -> SessionRecord | None:
        item = self._rows.get(owner_id, session_id)
        if item is None or (item["status"] == "deleting" and not include_deleting):
            return None
        return self._from_item(item)

    def list(self, owner_id: str) -> list[SessionRecord]:
        # One user's sessions are few; filtering and ordering here avoids an index nothing else needs.
        mine = [self._from_item(i) for i in self._rows.query(owner_id) if i["status"] == "active"]
        return sorted(mine, key=lambda r: r.created_at, reverse=True)

    def update(self, record: SessionRecord, expected_revision: int) -> SessionRecord:
        return self._from_item(self._rows.replace(self._to_item(record), expected_revision))

    def delete(self, owner_id: str, session_id: str) -> None:
        self._rows.delete(owner_id, session_id)


class DynamoItemStore:
    def __init__(self, table: Any) -> None:
        self._rows = OwnedTable(table, "item_id", "item")

    @staticmethod
    def _to_item(r: ItemRecord) -> dict[str, Any]:
        return {
            OWNER: r.owner_id,
            "item_id": r.item_id,
            "name": r.name,
            "description": r.description,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "revision": r.revision,
        }

    @staticmethod
    def _from_item(i: dict[str, Any]) -> ItemRecord:
        return ItemRecord(
            item_id=i["item_id"],
            owner_id=i[OWNER],
            name=i["name"],
            description=i.get("description"),
            created_at=i["created_at"],
            updated_at=i["updated_at"],
            revision=int(i["revision"]),
        )

    def create(self, record: ItemRecord) -> None:
        self._rows.create(self._to_item(record))

    def get(self, owner_id: str, item_id: str) -> ItemRecord | None:
        item = self._rows.get(owner_id, item_id)
        return None if item is None else self._from_item(item)

    def list(self, owner_id: str) -> list[ItemRecord]:
        return sorted((self._from_item(i) for i in self._rows.query(owner_id)), key=lambda r: r.created_at, reverse=True)

    def update(self, record: ItemRecord, expected_revision: int) -> ItemRecord:
        return self._from_item(self._rows.replace(self._to_item(record), expected_revision))

    def delete(self, owner_id: str, item_id: str) -> None:
        self._rows.delete(owner_id, item_id)
