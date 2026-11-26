"""Removes the protocol markers some models leak into their text.

A marker can arrive split across two streamed fragments, so the filter holds back
only the tail of the text that could still become the start of a marker, and
nothing else: ordinary text is released as soon as it is seen.
"""

from collections.abc import Sequence

# The one place to add a marker. The first three are DeepSeek's tool-call opener
# (full-width bars, the same with an escaped underscore, and plain ASCII).
PROTOCOL_MARKERS: tuple[str, ...] = (
    "<｜DSML｜function_calls",
    "<｜DSML｜function\\_calls",
    "<|DSML|function_calls",
)


class MarkerFilter:
    def __init__(self, markers: Sequence[str] = PROTOCOL_MARKERS) -> None:
        self._markers = tuple(m for m in markers if m)
        self._held = ""

    def feed(self, text: str) -> str:
        """Returns the part of the text that is already safe to emit."""
        buffer = self._strip(self._held + text)
        keep = self._partial_marker_length(buffer)
        self._held = buffer[len(buffer) - keep :] if keep else ""
        return buffer[: len(buffer) - keep]

    def flush(self) -> str:
        """End of stream: whatever is held can no longer become a marker, so it is text."""
        released, self._held = self._strip(self._held), ""
        return released

    def _strip(self, text: str) -> str:
        for marker in self._markers:
            text = text.replace(marker, "")
        return text

    def _partial_marker_length(self, text: str) -> int:
        longest = max((len(m) for m in self._markers), default=1) - 1
        for size in range(min(len(text), longest), 0, -1):
            tail = text[-size:]
            if any(m.startswith(tail) for m in self._markers):
                return size
        return 0
