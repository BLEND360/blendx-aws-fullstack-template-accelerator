"""Recorded InvokeHarness streams, as the stand-in harness and the translator tests replay them."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_DIR = Path(__file__).parent


def load(name: str) -> list[list[dict[str, Any]]]:
    """The invocations of a fixture: one list of raw stream events per call to the harness."""
    return json.loads((_DIR / f"{name}.json").read_text(encoding="utf-8"))["streams"]


_STREAM_ERROR_EVENTS = ("internalServerException", "validationException", "runtimeClientError")


def replay(events: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Yield a recorded stream the way botocore delivers it: an error event is raised
    as an EventStreamError (a ClientError) at that point of the iteration, not yielded."""
    from botocore.eventstream import EventStreamError

    for event in events:
        (name, body), = event.items()
        if name in _STREAM_ERROR_EVENTS:
            raise EventStreamError({"Error": {"Code": name, "Message": body.get("message", "")}}, "InvokeHarness")
        yield event
