"""A harness that plays recorded answers, for demonstrations and for working without AWS.

It is a HarnessPort like any other: the recorded raw streams go through the same
translator and marker filter as a live harness's, so the events, their order and the
errors are the real vocabulary. The answer does not depend on the question: a message
that contains the word "tool" plays the recorded turn that calls a tool; anything else
plays the recorded text turn. The conversation is written to an in-process memory so
the history still works after a reload.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from app.core.models import HarnessEvent, HarnessRequest, MemoryRef, TextDelta, TurnEnded
from app.harness import fixtures
from app.harness.fake import FakeMemory
from app.harness.text_filter import MarkerFilter
from app.harness.translate import translate

TEXT_TURN = "real_text_only"
TOOL_TURN = "real_tool_call"  # two streams: the tool call, then the answer to its result


class ReplayHarness:
    """Satisfies services.ports.HarnessPort."""

    def __init__(self, memory: FakeMemory, *, event_delay_seconds: float = 0.04) -> None:
        self._memory = memory
        self._delay = event_delay_seconds  # recorded events arrive in an instant; a pause makes the streaming visible

    def _remember(self, ref: MemoryRef, role: str, text: str) -> None:
        self._memory.add(ref, role, text, datetime.now(UTC).isoformat())

    def _pick(self, request: HarnessRequest) -> tuple[list[dict], str | None]:
        """The recorded stream to play, and the user's text when this call starts a new turn."""
        if request.messages[-1].tool_results:  # the second call of a tool turn: the answer to the tool's result
            return fixtures.load(TOOL_TURN)[1], None
        text = next((m.text for m in reversed(request.messages) if m.role == "user" and m.text), "")
        name = TOOL_TURN if "tool" in text.lower() else TEXT_TURN
        return fixtures.load(name)[0], text

    async def invoke(self, request: HarnessRequest) -> AsyncIterator[HarnessEvent]:
        stream, user_text = self._pick(request)
        if user_text is not None:
            self._remember(request.memory, "USER", user_text)
        said: list[str] = []
        needs_tools = False
        for event in translate(fixtures.replay(stream), MarkerFilter()):
            if isinstance(event, TextDelta):
                said.append(event.text)
            elif isinstance(event, TurnEnded):
                needs_tools = event.needs_tools
            yield event
            if not isinstance(event, TurnEnded) and self._delay:
                await asyncio.sleep(self._delay)
        if said and not needs_tools:  # the turn's final answer is what the history keeps
            self._remember(request.memory, "ASSISTANT", "".join(said))
