"""The harness's managed memory: where a conversation's content lives.

Finds the memory through GetHarness (the harness owns it; the backend never
stores its id), reads a session's events across every page, and deletes them.
Every failure leaves as AppError with a `memory_*` code.
"""

import threading
from collections.abc import Callable, Iterator
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.errors import MEMORY, AppError, MisconfiguredError, classify_aws_error
from app.core.models import MemoryEvent, MemoryRef

_PAGE = 100  # the largest ListEvents page
# Reads are idempotent, so unlike an invocation they may retry.
_CONFIG = Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2})


def _default_client(service: str) -> Any:
    return boto3.Session(region_name=settings.aws_region).client(service, config=_CONFIG)


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class AgentCoreMemory:
    """Satisfies services.ports.MemoryPort."""

    def __init__(self, harness_arn: str, *, client_factory: Callable[[str], Any] = _default_client) -> None:
        self._harness_arn = harness_arn
        self._factory = client_factory
        self._memory_id: str | None = None
        self._lock = threading.Lock()

    # --- discovery -------------------------------------------------------------------
    def _memory(self) -> str:
        with self._lock:
            if self._memory_id is None:
                self._memory_id = self._discover()
            return self._memory_id

    def _discover(self) -> str:
        if not self._harness_arn:
            raise MisconfiguredError(
                "Conversation history is not set up for this deployment.", dependency=MEMORY, detail="HARNESS_ARN is empty"
            )
        try:
            harness = self._factory("bedrock-agentcore-control").get_harness(harnessId=self._harness_arn.rsplit("/", 1)[-1])
        except Exception as exc:  # noqa: BLE001
            raise classify_aws_error(exc, dependency=MEMORY) from exc
        configuration = harness["harness"].get("memory") or {}
        for kind in ("managedMemoryConfiguration", "agentCoreMemoryConfiguration"):
            arn = (configuration.get(kind) or {}).get("arn", "")
            if "memory/" in arn:
                return arn.split("memory/", 1)[1]
        raise MisconfiguredError(
            "Conversation history is not set up for this deployment.",
            dependency=MEMORY,
            detail=f"the harness has no memory ({', '.join(configuration) or 'none'})",
        )

    # --- reads -----------------------------------------------------------------------
    def _pages(self, memory: MemoryRef, *, payloads: bool) -> Iterator[dict[str, Any]]:
        data = self._factory("bedrock-agentcore")
        memory_id = self._memory()
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "memoryId": memory_id,
                "actorId": memory.actor_id,
                "sessionId": memory.runtime_session_id,
                "includePayloads": payloads,
                "maxResults": _PAGE,
            }
            if token:
                kwargs["nextToken"] = token
            try:
                page = data.list_events(**kwargs)
            except Exception as exc:  # noqa: BLE001
                raise (exc if isinstance(exc, AppError) else classify_aws_error(exc, dependency=MEMORY)) from exc
            yield from page.get("events", [])
            token = page.get("nextToken")
            if not token:
                return

    def list_events(self, memory: MemoryRef) -> Iterator[MemoryEvent]:
        for event in self._pages(memory, payloads=True):
            timestamp, event_id = _iso(event.get("eventTimestamp", "")), str(event.get("eventId", ""))
            conversational = [p["conversational"] for p in event.get("payload", []) if "conversational" in p]
            if not conversational:
                yield MemoryEvent(event_id, timestamp, "OTHER", None)  # a blob or json payload: not part of the history
            for item in conversational:
                yield MemoryEvent(event_id, timestamp, str(item.get("role", "OTHER")), (item.get("content") or {}).get("text"))

    # --- deletion --------------------------------------------------------------------
    def purge(self, memory: MemoryRef) -> None:
        """Delete every event of the session, one call each: AgentCore has no delete-by-session.

        Safe to run again after a failure part-way: what is already gone is simply not listed.
        """
        data = self._factory("bedrock-agentcore")
        event_ids = [str(e["eventId"]) for e in self._pages(memory, payloads=False)]  # listed first, then deleted
        for event_id in event_ids:
            try:
                data.delete_event(
                    memoryId=self._memory(), actorId=memory.actor_id, sessionId=memory.runtime_session_id, eventId=event_id
                )
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                    continue  # deleted meanwhile (a concurrent retry): the goal is met
                raise classify_aws_error(exc, dependency=MEMORY) from exc
            except Exception as exc:  # noqa: BLE001
                raise (exc if isinstance(exc, AppError) else classify_aws_error(exc, dependency=MEMORY)) from exc
