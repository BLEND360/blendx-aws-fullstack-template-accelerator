"""A session's past messages, read from the harness's memory and nowhere else.

Ownership is checked first: a session that is not the caller's is a 404 before
the memory is touched, so history cannot be used to probe other users' ids.
"""

from dataclasses import dataclass
from typing import Literal

from app.core.errors import NotFoundError
from app.core.models import MemoryEvent
from app.services.ports import MemoryPort, SessionStore
from app.services.sessions import NOT_FOUND

_ROLES: dict[str, Literal["user", "assistant"]] = {"USER": "user", "ASSISTANT": "assistant"}


@dataclass(frozen=True)
class HistoryMessage:
    role: Literal["user", "assistant"]
    text: str
    created_at: str


def _order(event: MemoryEvent) -> tuple[str, int, str]:
    # Event ids look like "<sequence>#<hex>": compare the sequence as a number, so 10 follows 9.
    sequence = event.event_id.split("#", 1)[0]
    return event.timestamp, int(sequence) if sequence.isdigit() else 0, event.event_id


class HistoryService:
    def __init__(self, store: SessionStore, memory: MemoryPort) -> None:
        self._store, self._memory = store, memory

    def get(self, owner_id: str, session_id: str) -> list[HistoryMessage]:
        record = self._store.get(owner_id, session_id)
        if record is None:
            raise NotFoundError(NOT_FOUND)
        events = sorted(self._memory.list_events(record.memory), key=_order)
        return [
            HistoryMessage(_ROLES[e.role], e.text, e.timestamp)
            for e in events
            if e.role in _ROLES and e.text  # tool and other events are not conversation
        ]
