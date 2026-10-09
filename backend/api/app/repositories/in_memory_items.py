"""Items held in this process: the local default, and the stand-in service tests use.

Same contract as services.ports.ItemStore, which tests/test_store_contract.py runs against this
and the DynamoDB adapter alike. Correct for one process only.
"""

import threading
from dataclasses import replace

from app.core.errors import DATA, ConflictError, NotFoundError
from app.core.models import ItemRecord

_CHANGED = "This item changed since you loaded it. Reload and try again."


class InMemoryItemStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], ItemRecord] = {}
        self._lock = threading.Lock()

    def create(self, record: ItemRecord) -> None:
        key = (record.owner_id, record.item_id)
        with self._lock:
            if key in self._records:
                raise ConflictError(_CHANGED, dependency=DATA, detail="item id already exists")
            self._records[key] = record

    def get(self, owner_id: str, item_id: str) -> ItemRecord | None:
        return self._records.get((owner_id, item_id))

    def list(self, owner_id: str) -> list[ItemRecord]:
        with self._lock:
            mine = [r for (owner, _), r in self._records.items() if owner == owner_id]
        return sorted(mine, key=lambda r: r.created_at, reverse=True)

    def update(self, record: ItemRecord, expected_revision: int) -> ItemRecord:
        key = (record.owner_id, record.item_id)
        with self._lock:
            stored = self._records.get(key)
            if stored is None:
                raise NotFoundError("Item not found.")
            if stored.revision != expected_revision:
                raise ConflictError(
                    _CHANGED, dependency=DATA, detail=f"expected revision {expected_revision}, found {stored.revision}"
                )
            saved = replace(record, revision=expected_revision + 1)
            self._records[key] = saved
            return saved

    def delete(self, owner_id: str, item_id: str) -> None:
        with self._lock:
            self._records.pop((owner_id, item_id), None)
