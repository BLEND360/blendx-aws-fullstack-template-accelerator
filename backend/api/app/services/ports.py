"""Ports: what services need from the outside, as types.

Declared here, in the layer that owns the need, and implemented in clients/,
repositories/ and harness/. Services compose these, never concrete adapters,
so every service is testable with a stand-in and no AWS.
"""

from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Protocol

from app.core.models import (
    HarnessEvent,
    HarnessRequest,
    MemoryEvent,
    MemoryRef,
    SessionRecord,
    ToolOutcome,
    ToolSpec,
)


class DependencyProbe(Protocol):
    """One reachability check for /ready. Raises AppError when unreachable."""

    name: str

    def check(self) -> None: ...


class HarnessPort(Protocol):
    """Runs one invocation of the configured harness and yields what it produced.

    Raises AppError from the iterator for any failure, including those that arrive
    inside the stream. Cancelling the consumer cancels the invocation.
    """

    def invoke(self, request: HarnessRequest) -> AsyncIterator[HarnessEvent]: ...


class MemoryPort(Protocol):
    """The harness's memory: the only place a conversation's content lives."""

    def list_events(self, memory: MemoryRef) -> Iterator[MemoryEvent]:
        """Every event of the session, across all pages."""
        ...

    def purge(self, memory: MemoryRef) -> None:
        """Delete every event of the session. Safe to call again after a partial failure."""
        ...


class SessionStore(Protocol):
    """Session metadata, owned by the caller: (owner_id, session_id) is the key.

    ST-05 provides the DynamoDB implementation. Errors surface as AppError
    (`data_unavailable`, `data_throttled`, `data_conflict`).
    """

    def create(self, record: SessionRecord) -> None: ...

    def get(self, owner_id: str, session_id: str, *, include_deleting: bool = False) -> SessionRecord | None: ...

    def list(self, owner_id: str) -> list[SessionRecord]:
        """Only status "active"."""
        ...

    def update(self, record: SessionRecord, expected_revision: int) -> SessionRecord:
        """Atomic: ConflictError when the stored revision differs. Returns the record with revision + 1."""
        ...

    def delete(self, owner_id: str, session_id: str) -> None: ...


class ToolPort(Protocol):
    """Local tools the agent may call. Ids are what the client sends; everything executable is resolved here."""

    def ids(self) -> frozenset[str]: ...

    def label(self, tool_id: str) -> str | None: ...

    def specs_for(self, tool_ids: Sequence[str]) -> tuple[ToolSpec, ...]: ...

    def run(self, tool_id: str, raw_input: dict[str, object] | None) -> ToolOutcome:
        """Never raises: a failure is a ToolOutcome with status "error"."""
        ...
