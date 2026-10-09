"""One conversation turn: send the user's message, relay what the agent does, run local tools.

`prepare` runs before any response is sent, so a wrong session, an empty message
or an unconfigured harness are ordinary HTTP errors. `run` runs after the stream
is open: it never raises, it ends with exactly one `done` or one `error`.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass

from app.core.context import get_request_id
from app.core.errors import (
    HARNESS,
    TOOL,
    AppError,
    MisconfiguredError,
    NotFoundError,
    ToolFailedError,
    ValidationFailedError,
)
from app.core.logging import get_logger
from app.core.models import (
    Delta,
    Done,
    ErrorEvent,
    HarnessMessage,
    HarnessRequest,
    ManagedToolResult,
    SessionRecord,
    TextDelta,
    ToolCall,
    ToolCallReady,
    ToolCallStarted,
    ToolFinished,
    ToolInput,
    ToolOutcome,
    ToolResultBlock,
    ToolStarted,
    TurnEnded,
    TurnEvent,
)
from app.services.ports import HarnessPort, SessionStore, ToolPort
from app.services.sessions import NOT_FOUND

logger = get_logger(__name__)

_TOOL_FAILED = {"code": "tool_failed"}


@dataclass(frozen=True)
class PreparedTurn:
    record: SessionRecord
    text: str


class TurnService:
    def __init__(
        self, store: SessionStore, harness: HarnessPort, tools: ToolPort, *, harness_arn: str, max_tool_rounds: int
    ) -> None:
        self._store, self._harness, self._tools = store, harness, tools
        self._harness_arn, self._max_rounds = harness_arn, max_tool_rounds

    def prepare(self, owner_id: str, session_id: str, text: str) -> PreparedTurn:
        """Everything that can be refused as an ordinary HTTP error, before a stream exists."""
        if not text.strip():
            raise ValidationFailedError(
                "The request is not valid.", fields=[{"location": "body.text", "message": "Message is empty."}]
            )
        record = self._store.get(owner_id, session_id)
        if record is None:
            raise NotFoundError(NOT_FOUND)
        if not self._harness_arn:
            raise MisconfiguredError(
                "No assistant is configured for this deployment.", dependency=HARNESS, detail="HARNESS_ARN is empty"
            )
        return PreparedTurn(record=record, text=text)

    async def run(self, turn: PreparedTurn) -> AsyncIterator[TurnEvent]:
        record = turn.record
        values = record.config.values  # frozen at creation or last update: template changes since do not apply
        enabled = set(values.tool_ids)
        specs = self._tools.specs_for(values.tool_ids)
        messages = [HarnessMessage("user", text=turn.text)]
        rounds = 0
        answered: set[str] = set()  # calls whose result this service supplied
        logger.info("turn_started", session_id=record.session_id, model_id=values.model_id)
        try:
            while True:
                ready: dict[str, ToolCallReady] = {}  # calls the model finished describing
                managed: set[str] = set()  # calls the harness already ran itself
                needs_tools = False
                request = HarnessRequest(record.memory, values.model_id, specs, tuple(messages))
                # aclosing: a client that disconnects closes the harness stream right here, not at garbage collection.
                async with aclosing(self._harness.invoke(request)) as stream:
                    async for event in stream:
                        if isinstance(event, TextDelta):
                            yield Delta(event.text)
                        elif isinstance(event, ToolCallStarted):
                            yield ToolStarted(event.call_id, event.name, self._tools.label(event.name) or event.name)
                        elif isinstance(event, ToolCallReady):
                            ready[event.call_id] = event
                            yield ToolInput(event.call_id, event.input or {})
                        elif isinstance(event, ManagedToolResult):
                            if event.call_id in answered:
                                continue  # the harness echoing back the result we just sent: already announced
                            managed.add(event.call_id)
                            yield ToolFinished(event.call_id, event.status, event.content)
                        elif isinstance(event, TurnEnded):
                            needs_tools = event.needs_tools

                pending = [call for call_id, call in ready.items() if call_id not in managed]
                if not (needs_tools and pending):
                    break

                rounds += 1
                if rounds > self._max_rounds:
                    raise ToolFailedError(
                        "The assistant used too many tool steps.", dependency=TOOL, detail=f"more than {self._max_rounds} tool rounds"
                    )
                results: list[ToolResultBlock] = []
                for call in pending:
                    outcome = await self._run_tool(call, enabled)
                    yield ToolFinished(call.call_id, outcome.status, outcome.public_result)
                    results.append(ToolResultBlock(call.call_id, outcome.status, outcome.result))
                    answered.add(call.call_id)
                messages = [
                    HarnessMessage("assistant", tool_calls=tuple(ToolCall(c.call_id, c.name, c.input or {}) for c in pending)),
                    HarnessMessage("user", tool_results=tuple(results)),
                ]
            yield Done()
        except Exception as exc:  # noqa: BLE001 - a turn that fails after the stream opened must still end with an event
            if isinstance(exc, AppError):
                code, retryable = exc.code, exc.retryable
                logger.error("turn_failed", session_id=record.session_id, code=code, detail=exc.detail or exc.message)
            else:
                code, retryable = "internal_error", False
                logger.exception("turn_failed", session_id=record.session_id, code=code)
            yield ErrorEvent(code, retryable, get_request_id())

    async def _run_tool(self, call: ToolCallReady, enabled: set[str]) -> ToolOutcome:
        if call.name not in enabled:
            # Unknown, or known but not enabled for this session: the model gets a failure and carries on.
            logger.warning("tool_failed", tool=call.name, reason="not_enabled_for_session")
            return ToolOutcome("error", dict(_TOOL_FAILED), dict(_TOOL_FAILED))
        # Off the event loop: a handler may block. The thread inherits the request id.
        return await asyncio.to_thread(self._tools.run, call.name, call.input)
