"""A session's runtime configuration: template defaults + the caller's overrides, validated and frozen.

Pure: no I/O, so creation and update share one rule set and are testable alone.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.core.errors import ValidationFailedError
from app.core.models import RuntimeValues, SessionConfig


class _Unset:
    """Marks a field the caller left out, which is not the same as an explicit null."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = _Unset()


@dataclass(frozen=True)
class Overrides:
    # UNSET keeps the current value; None restores the default frozen at creation.
    model_id: str | None | _Unset = UNSET
    tool_ids: Sequence[str] | None | _Unset = UNSET


def template_defaults(allowed_model_ids: Sequence[str], tool_ids: Sequence[str]) -> RuntimeValues:
    """The template's defaults: the first allowed model and every registered tool."""
    return RuntimeValues(model_id=allowed_model_ids[0], tool_ids=tuple(tool_ids))


def resolve(
    defaults: RuntimeValues,
    allowed_model_ids: Sequence[str],
    known_tool_ids: frozenset[str],
    overrides: Overrides,
    current: SessionConfig | None = None,
) -> SessionConfig:
    """Creation when `current` is None; otherwise an update of `current`.

    Only values being set (explicitly, or restored by null) are validated: a field
    left out keeps working even if the template's allowlist shrank since creation.
    """
    frozen = defaults if current is None else current.frozen_defaults
    base = defaults if current is None else current.values
    problems: list[dict[str, str]] = []

    model_id = base.model_id
    if not isinstance(overrides.model_id, _Unset):
        model_id = frozen.model_id if overrides.model_id is None else overrides.model_id
        if model_id not in allowed_model_ids:
            problems.append({"location": "body.modelId", "message": "Model is not allowed."})

    tool_ids = base.tool_ids
    if not isinstance(overrides.tool_ids, _Unset):
        requested = frozen.tool_ids if overrides.tool_ids is None else tuple(overrides.tool_ids)
        tool_ids = tuple(dict.fromkeys(requested))  # drop duplicates, keep order
        problems.extend(
            {"location": f"body.toolIds.{i}", "message": "Unknown tool."}
            for i, tool_id in enumerate(tool_ids)
            if tool_id not in known_tool_ids
        )

    if problems:
        raise ValidationFailedError(fields=problems)
    return SessionConfig(values=RuntimeValues(model_id=model_id, tool_ids=tool_ids), frozen_defaults=frozen)
