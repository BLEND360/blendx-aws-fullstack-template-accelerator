"""The tools this deployment offers. Adding one is adding an entry to TOOLS."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.tools.registry import Tool, ToolRegistry


class CurrentTimeInput(BaseModel):
    format: Literal["iso", "unix"] = Field(default="iso", description="ISO 8601 text or Unix seconds.")


def make_current_time(clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> Callable[[CurrentTimeInput], dict[str, str | int]]:
    """The example tool. The clock is injectable so its test does not depend on the time it runs."""

    def current_time(arguments: CurrentTimeInput) -> dict[str, str | int]:
        now = clock()
        return {"time": now.isoformat()} if arguments.format == "iso" else {"time": int(now.timestamp())}

    return current_time


TOOLS: list[Tool] = [
    Tool(
        id="current_time",
        label="Checking the time",
        description="Returns the current UTC time.",
        input_model=CurrentTimeInput,
        handler=make_current_time(),
    ),
]

registry = ToolRegistry(TOOLS)
