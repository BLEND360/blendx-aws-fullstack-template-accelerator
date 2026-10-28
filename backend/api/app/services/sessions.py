"""A user's conversations: create, list, read, adjust and delete.

Everything here is scoped to the owner the router took from the authenticated
identity; there is no way to name another user's session, and one that does not
exist and one that is someone else's look identical.
"""

import hashlib
import uuid
from collections.abc import Callable, Sequence
from dataclasses import replace

from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.core.models import MemoryRef, RuntimeValues, SessionRecord
from app.core.stamps import new_id, utc_now
from app.services.ports import MemoryPort, SessionStore, ToolPort
from app.services.runtime_config import Overrides, resolve, template_defaults

logger = get_logger(__name__)

NOT_FOUND = "Session not found."


class SessionService:
    def __init__(
        self,
        store: SessionStore,
        memory: MemoryPort,
        tools: ToolPort,
        *,
        allowed_model_ids: Sequence[str],
        now: Callable[[], str] = utc_now,
        new_id: Callable[[], str] = new_id,
    ) -> None:
        self._store, self._memory, self._tools = store, memory, tools
        self._allowed = list(allowed_model_ids)
        self._now, self._new_id = now, new_id

    def _defaults(self) -> RuntimeValues:
        return template_defaults(self._allowed, sorted(self._tools.ids()))

    @staticmethod
    def _memory_ref(owner_id: str, new_id: Callable[[], str]) -> MemoryRef:
        # Both satisfy AgentCore's patterns: a runtime session id is 33-100 characters.
        # The random suffix keeps it above 33 even when a caller injects a short `new_id`.
        return MemoryRef(
            runtime_session_id="s-" + new_id() + uuid.uuid4().hex[:2],
            actor_id="u-" + hashlib.sha256(owner_id.encode()).hexdigest()[:32],
        )

    def create(self, owner_id: str, overrides: Overrides) -> SessionRecord:
        config = resolve(self._defaults(), self._allowed, self._tools.ids(), overrides)
        now = self._now()
        record = SessionRecord(
            session_id=self._new_id(),
            owner_id=owner_id,
            status="active",
            config=config,
            memory=self._memory_ref(owner_id, self._new_id),
            created_at=now,
            updated_at=now,
            revision=1,
        )
        self._store.create(record)
        return record

    def list(self, owner_id: str) -> list[SessionRecord]:
        return self._store.list(owner_id)

    def get(self, owner_id: str, session_id: str) -> SessionRecord:
        record = self._store.get(owner_id, session_id)
        if record is None:
            raise NotFoundError(NOT_FOUND)
        return record

    def update(self, owner_id: str, session_id: str, overrides: Overrides) -> SessionRecord:
        record = self.get(owner_id, session_id)
        config = resolve(self._defaults(), self._allowed, self._tools.ids(), overrides, record.config)
        # Two updates that read the same revision cannot both write: the second finds it moved.
        return self._store.update(replace(record, config=config, updated_at=self._now()), record.revision)

    def delete(self, owner_id: str, session_id: str) -> None:
        """Memory first, then metadata. If the memory cannot be emptied the session stays
        `deleting` (hidden everywhere) and the next call resumes from here."""
        record = self._store.get(owner_id, session_id, include_deleting=True)
        if record is None:
            raise NotFoundError(NOT_FOUND)
        if record.status == "active":
            record = self._store.update(replace(record, status="deleting", updated_at=self._now()), record.revision)
        try:
            self._memory.purge(record.memory)
        except AppError as exc:
            logger.warning("memory_purge_failed", session_id=session_id, code=exc.code, detail=exc.detail)
            raise
        self._store.delete(owner_id, session_id)
