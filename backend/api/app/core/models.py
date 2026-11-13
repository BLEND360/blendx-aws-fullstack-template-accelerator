"""Types that cross layers: the vocabulary services, adapters and routers share.

Plain frozen dataclasses with no behavior. They live in core because adapters
(a lower layer) must produce them and services (an upper layer) must consume
them, and an adapter cannot import from services.
"""

from dataclasses import dataclass
from typing import Any, Final, Literal, Union

Status = Literal["success", "error"]


# --- Sessions ---------------------------------------------------------------
@dataclass(frozen=True)
class RuntimeValues:
    model_id: str
    tool_ids: tuple[str, ...]


@dataclass(frozen=True)
class SessionConfig:
    values: RuntimeValues  # what every turn uses
    frozen_defaults: RuntimeValues  # the template's defaults at creation: where a null override goes back to


@dataclass(frozen=True)
class MemoryRef:
    """Where the conversation lives in the harness's memory. Never leaves the server."""

    runtime_session_id: str  # "s-" + uuid4().hex; also the memory's sessionId
    actor_id: str  # "u-" + sha256(owner_id).hexdigest()[:32]


@dataclass(frozen=True)
class SessionRecord:
    session_id: str  # opaque, generated on the server
    owner_id: str  # from the authenticated identity, never from a request
    status: Literal["active", "deleting"]
    config: SessionConfig
    memory: MemoryRef
    created_at: str  # ISO 8601 UTC
    updated_at: str
    revision: int  # optimistic concurrency; starts at 1


# --- What a harness adapter consumes and produces ---------------------------
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResultBlock:
    call_id: str
    status: Status
    content: dict[str, Any]


@dataclass(frozen=True)
class HarnessMessage:
    role: Literal["user", "assistant"]
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResultBlock, ...] = ()


@dataclass(frozen=True)
class HarnessRequest:
    memory: MemoryRef
    model_id: str
    tools: tuple[ToolSpec, ...]
    messages: tuple[HarnessMessage, ...]


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCallStarted:
    call_id: str
    name: str


@dataclass(frozen=True)
class ToolCallReady:
    call_id: str
    name: str
    input: dict[str, Any] | None  # None: the model produced input that is not valid JSON


@dataclass(frozen=True)
class ManagedToolResult:
    """A tool the harness ran itself (gateway, remote MCP): its result arrives in the same stream."""

    call_id: str
    name: str
    status: Status
    content: dict[str, Any]


@dataclass(frozen=True)
class TurnEnded:
    needs_tools: bool  # stopReason "tool_use": the caller must run local tools and invoke again


HarnessEvent = Union[TextDelta, ToolCallStarted, ToolCallReady, ManagedToolResult, TurnEnded]


@dataclass(frozen=True)
class MemoryEvent:
    """One event of the harness's memory, reduced to what history needs."""

    event_id: str
    timestamp: str
    role: str  # as memory reports it: USER, ASSISTANT, TOOL, OTHER
    text: str | None  # None for payloads that are not conversational


@dataclass(frozen=True)
class ToolOutcome:
    status: Status
    result: dict[str, Any]  # what the harness sees
    public_result: dict[str, Any]  # what the browser sees: redacted and bounded


# --- What the router serializes to SSE --------------------------------------
@dataclass(frozen=True)
class Delta:
    text: str


@dataclass(frozen=True)
class ToolStarted:
    call_id: str
    tool_id: str
    label: str


@dataclass(frozen=True)
class ToolInput:
    call_id: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolFinished:
    call_id: str
    status: Status
    result: dict[str, Any]


@dataclass(frozen=True)
class Done:
    pass


@dataclass(frozen=True)
class ErrorEvent:
    code: str
    retryable: bool
    request_id: str | None


TurnEvent = Union[Delta, ToolStarted, ToolInput, ToolFinished, Done, ErrorEvent]

# The closed vocabulary of a turn's event stream. tests/test_event_vocabulary.py
# pins it: adding, removing or renaming an event fails a test on purpose.
TURN_EVENT_NAMES: Final[dict[type, str]] = {
    Delta: "delta",
    ToolStarted: "tool_started",
    ToolInput: "tool_input",
    ToolFinished: "tool_finished",
    Done: "done",
    ErrorEvent: "error",
}
