"""A stand-in for AgentCore, for tests and for running the app with no AWS.

ReplayInvoker plays recorded raw streams where BotoInvoker would call
InvokeHarness, so the real translator, filter and error mapping run on them.
FakeMemory is the harness's memory held in a dict.
"""

from collections.abc import Iterator, Sequence
from typing import Any

from app.core.errors import AppError
from app.core.models import MemoryEvent, MemoryRef
from app.harness import fixtures


class ReplayInvoker:
    """Satisfies harness.client.RawInvoker. Each call returns the next recorded stream."""

    def __init__(self, streams: Sequence[list[dict[str, Any]]]) -> None:
        self._streams = list(streams)
        self.calls: list[dict[str, Any]] = []  # the parameters each invocation was given

    @classmethod
    def from_fixture(cls, name: str) -> "ReplayInvoker":
        return cls(fixtures.load(name))

    def invoke(self, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        self.calls.append(params)
        if len(self.calls) > len(self._streams):
            raise AssertionError(f"invocation {len(self.calls)} has no recorded stream (only {len(self._streams)})")
        return fixtures.replay(self._streams[len(self.calls) - 1])


class FakeMemory:
    """Satisfies services.ports.MemoryPort."""

    def __init__(self, events: dict[str, list[MemoryEvent]] | None = None) -> None:
        self.events: dict[str, list[MemoryEvent]] = events or {}  # keyed by the memory's session id
        self.purge_error: AppError | None = None  # set to make purge fail, clear to let a retry succeed
        self.list_calls = 0
        self.purge_calls = 0

    def add(self, memory: MemoryRef, role: str, text: str | None, timestamp: str, event_id: str | None = None) -> None:
        bucket = self.events.setdefault(memory.runtime_session_id, [])
        bucket.append(MemoryEvent(event_id or f"{len(bucket) + 1}#e", timestamp, role, text))

    def list_events(self, memory: MemoryRef) -> Iterator[MemoryEvent]:
        self.list_calls += 1
        yield from list(self.events.get(memory.runtime_session_id, []))

    def purge(self, memory: MemoryRef) -> None:
        self.purge_calls += 1
        if self.purge_error is not None:
            # A partial failure: half the events are already gone, like a real mid-purge error.
            bucket = self.events.get(memory.runtime_session_id, [])
            del bucket[: len(bucket) // 2]
            raise self.purge_error
        self.events.pop(memory.runtime_session_id, None)
