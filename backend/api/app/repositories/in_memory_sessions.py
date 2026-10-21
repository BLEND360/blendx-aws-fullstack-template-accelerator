"""Session metadata held in this process: the local default (see repositories/dynamo.py for the deployed store).

Same contract as services.ports.SessionStore, so swapping it is a change of
wiring, not of services. It is correct for one process only: with two tasks each
would see its own sessions, which is why the app logs a warning at startup.
"""

import threading
from dataclasses import replace

from app.core.errors import DATA, ConflictError, NotFoundError
from app.core.models import SessionRecord

_CHANGED = "This session changed since you loaded it. Reload and try again."


class InMemorySessionStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], SessionRecord] = {}
        self._lock = threading.Lock()

    def create(self, record: SessionRecord) -> None:
        key = (record.owner_id, record.session_id)
        with self._lock:
            if key in self._records:
                raise ConflictError(_CHANGED, dependency=DATA, detail="session id already exists")
            self._records[key] = record

    def get(self, owner_id: str, session_id: str, *, include_deleting: bool = False) -> SessionRecord | None:
        # The owner is part of the key: another user's id is simply absent.
        record = self._records.get((owner_id, session_id))
        if record is None or (record.status == "deleting" and not include_deleting):
            return None
        return record

    def list(self, owner_id: str) -> list[SessionRecord]:
        with self._lock:
            mine = [r for (owner, _), r in self._records.items() if owner == owner_id and r.status == "active"]
        return sorted(mine, key=lambda r: r.created_at, reverse=True)

    def update(self, record: SessionRecord, expected_revision: int) -> SessionRecord:
        key = (record.owner_id, record.session_id)
        with self._lock:
            stored = self._records.get(key)
            if stored is None:
                raise NotFoundError("Session not found.")
            if stored.revision != expected_revision:
                raise ConflictError(
                    _CHANGED, dependency=DATA, detail=f"expected revision {expected_revision}, found {stored.revision}"
                )
            saved = replace(record, revision=expected_revision + 1)
            self._records[key] = saved
            return saved

    def delete(self, owner_id: str, session_id: str) -> None:
        with self._lock:
            self._records.pop((owner_id, session_id), None)
