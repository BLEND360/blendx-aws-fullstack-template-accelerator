"""The example entity: a user's items. The template's worked example of an owned resource.

Like sessions, everything is scoped to the owner the router took from the authenticated
identity. An item that does not exist and one that belongs to someone else are the same 404.
"""

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from app.core.errors import NotFoundError
from app.core.models import ItemRecord
from app.services.ports import ItemStore

NOT_FOUND = "Item not found."


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


class ItemService:
    def __init__(
        self, store: ItemStore, *, now: Callable[[], str] = _utc_now, new_id: Callable[[], str] = _new_id
    ) -> None:
        self._store, self._now, self._new_id = store, now, new_id

    def create(self, owner_id: str, name: str, description: str | None) -> ItemRecord:
        now = self._now()
        record = ItemRecord(self._new_id(), owner_id, name, description, created_at=now, updated_at=now, revision=1)
        self._store.create(record)
        return record

    def list(self, owner_id: str) -> list[ItemRecord]:
        return self._store.list(owner_id)

    def get(self, owner_id: str, item_id: str) -> ItemRecord:
        record = self._store.get(owner_id, item_id)
        if record is None:
            raise NotFoundError(NOT_FOUND)
        return record

    def update(self, owner_id: str, item_id: str, changes: dict[str, Any]) -> ItemRecord:
        """`changes` holds only what the client sent (name, description); the rest is kept.
        Two updates that read the same revision cannot both write: the second finds it moved."""
        record = self.get(owner_id, item_id)
        return self._store.update(replace(record, **changes, updated_at=self._now()), record.revision)

    def delete(self, owner_id: str, item_id: str) -> None:
        self.get(owner_id, item_id)  # missing and foreign look alike
        self._store.delete(owner_id, item_id)
