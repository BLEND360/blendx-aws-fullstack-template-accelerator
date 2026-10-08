"""AgentCore's raw event stream -> the harness events services understand.

The only place that knows the shape of an InvokeHarness stream. A change in
AgentCore is a change here. Failures, including those that arrive inside an
open stream, leave as AppError with a fixed sentence; AgentCore's own text only
reaches `detail`, which is logged and never sent.
"""

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import (
    HARNESS,
    AppError,
    InvalidRequestError,
    UnavailableError,
    classify_aws_error,
)
from app.core.models import (
    HarnessEvent,
    ManagedToolResult,
    TextDelta,
    ToolCallReady,
    ToolCallStarted,
    TurnEnded,
)
from app.harness.text_filter import MarkerFilter

_SUCCESS = frozenset({"end_turn", "stop_sequence", "max_tokens", "max_output_tokens_exceeded"})
_RETRYABLE = frozenset({"timeout_exceeded", "interrupted", "partial_turn", "malformed_model_output", "malformed_tool_use"})
# Anything else (content_filtered, model_context_window_exceeded, max_iterations_exceeded,
# hook_stopped, tool_result, or a value this code has not seen) is not worth retrying as is.


@dataclass
class _Block:
    kind: str  # "toolUse" | "toolResult"
    call_id: str
    name: str = ""
    status: str = "success"
    input_text: str = ""
    parts: list[Any] = field(default_factory=list)


def _tool_input(text: str) -> dict[str, Any] | None:
    """What the model sent as a tool's arguments: a JSON object, or None if it is not one."""
    if not text.strip():
        return {}
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _stop(reason: str) -> TurnEnded:
    if reason in _SUCCESS:
        return TurnEnded(needs_tools=False)
    if reason == "tool_use":
        return TurnEnded(needs_tools=True)
    detail = f"stopReason={reason}"
    if reason in _RETRYABLE:
        raise UnavailableError("The assistant is temporarily unavailable.", dependency=HARNESS, detail=detail)
    raise InvalidRequestError("The assistant rejected the request.", dependency=HARNESS, detail=detail)


def translate(raw: Iterable[dict[str, Any]], marker_filter: MarkerFilter) -> Iterator[HarnessEvent]:
    blocks: dict[int, _Block] = {}
    names: dict[str, str] = {}  # call id -> tool name, to label a managed result
    try:
        for event in raw:
            (kind, body), = event.items()
            if kind == "contentBlockStart":
                start = body.get("start", {})
                if "toolUse" in start:
                    use = start["toolUse"]
                    names[use["toolUseId"]] = use["name"]
                    blocks[body["contentBlockIndex"]] = _Block("toolUse", use["toolUseId"], use["name"])
                    yield ToolCallStarted(use["toolUseId"], use["name"])
                elif "toolResult" in start:
                    result = start["toolResult"]
                    blocks[body["contentBlockIndex"]] = _Block(
                        "toolResult", result["toolUseId"], names.get(result["toolUseId"], ""), result.get("status", "success")
                    )
            elif kind == "contentBlockDelta":
                delta, block = body["delta"], blocks.get(body["contentBlockIndex"])
                if "text" in delta:
                    if text := marker_filter.feed(delta["text"]):
                        yield TextDelta(text)
                elif "toolUse" in delta and block and block.kind == "toolUse":
                    block.input_text += delta["toolUse"].get("input", "")
                elif "toolResult" in delta and block and block.kind == "toolResult":
                    block.parts.extend(delta["toolResult"])
            elif kind == "contentBlockStop":
                block = blocks.pop(body["contentBlockIndex"], None)
                if block and block.kind == "toolUse":
                    yield ToolCallReady(block.call_id, block.name, _tool_input(block.input_text))
                elif block and block.kind == "toolResult":
                    status = "success" if block.status == "success" else "error"
                    yield ManagedToolResult(block.call_id, block.name, status, {"content": block.parts})
            elif kind == "messageStop":
                if tail := marker_filter.flush():
                    yield TextDelta(tail)
                yield _stop(body["stopReason"])
                return
            # messageStart, metadata, hookEvent and reasoning content carry nothing the browser sees.
        # The stream closed without a messageStop: the turn did not finish, whatever was said so far.
        raise UnavailableError(
            "The assistant is temporarily unavailable.", dependency=HARNESS, detail="stream ended without messageStop"
        )
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001 - botocore raises in-stream errors and broken connections as ClientError/BotoCoreError
        raise classify_aws_error(exc, dependency=HARNESS) from exc
