"""Local tools: capabilities the agent can call that run in this process.

A tool is declared once, with its name, an input model (which is both the JSON
schema the harness sees and the validation of what the model sends back) and the
function that runs it. The client only ever names a tool by id; everything
executable is resolved here, on the server.
"""

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.core.logging import get_logger
from app.core.models import ToolOutcome, ToolSpec

logger = get_logger(__name__)

# The harness accepts [a-zA-Z0-9_-]{1,64} as a tool name.
_TOOL_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
# What the browser may be sent of a tool result.
MAX_PUBLIC_RESULT_BYTES = 16 * 1024

_FAILED = {"code": "tool_failed"}


@dataclass(frozen=True)
class Tool:
    id: str
    label: str  # shown to the user while the tool runs
    description: str  # shown to the model
    input_model: type[BaseModel]
    handler: Callable[[Any], Any]  # receives an input_model; returns a dict or a BaseModel


def _failure() -> ToolOutcome:
    return ToolOutcome(status="error", result=dict(_FAILED), public_result=dict(_FAILED))


class ToolRegistry:
    """Satisfies services.ports.ToolPort."""

    def __init__(self, tools: Sequence[Tool]) -> None:
        by_id: dict[str, Tool] = {}
        for tool in tools:
            if not _TOOL_ID.match(tool.id):
                raise ValueError(f"tool id {tool.id!r} must match [a-zA-Z0-9_-]{{1,64}}")
            if tool.id in by_id:
                raise ValueError(f"tool id {tool.id!r} is declared twice")
            by_id[tool.id] = tool
        self._tools = by_id

    def ids(self) -> frozenset[str]:
        return frozenset(self._tools)

    def label(self, tool_id: str) -> str | None:
        tool = self._tools.get(tool_id)
        return tool.label if tool else None

    def specs_for(self, tool_ids: Sequence[str]) -> tuple[ToolSpec, ...]:
        return tuple(
            ToolSpec(name=t.id, description=t.description, input_schema=t.input_model.model_json_schema())
            for t in (self._tools[i] for i in tool_ids if i in self._tools)
        )

    def run(self, tool_id: str, raw_input: dict[str, Any] | None) -> ToolOutcome:
        """Never raises: unknown tool, unusable input and a handler that throws are all a `tool_failed` outcome."""
        tool = self._tools.get(tool_id)
        if tool is None or raw_input is None:
            logger.warning("tool_failed", tool=tool_id, reason="unknown_tool" if tool is None else "input_not_json")
            return _failure()
        try:
            arguments = tool.input_model.model_validate(raw_input)
        except Exception as exc:  # noqa: BLE001 - the model's input is untrusted
            logger.warning("tool_failed", tool=tool_id, reason="invalid_input", error=type(exc).__name__)
            return _failure()
        try:
            output = tool.handler(arguments)
            result = output.model_dump(mode="json") if isinstance(output, BaseModel) else output
            encoded = json.dumps(result)
        except Exception:  # noqa: BLE001 - a tool is third-party code from this layer's point of view
            logger.exception("tool_failed", tool=tool_id, reason="handler_error")
            return _failure()
        public = result if len(encoded.encode()) <= MAX_PUBLIC_RESULT_BYTES else {"truncated": True}
        return ToolOutcome(status="success", result=result, public_result=public)
