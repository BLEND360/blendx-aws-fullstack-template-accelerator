"""A turn can sit silent for a long time while the agent thinks, and CloudFront closes a connection after 60 s
without a byte. FastAPI's `EventSourceResponse` writes a `: ping` comment whenever the stream has been idle for
`_PING_INTERVAL`, which is what keeps the turn alive through CloudFront. The deployment (app-stack) relies on it
and writes none of its own, so this pins the two facts it depends on: that the interval stays well inside
CloudFront's window, and that the turn route really is served by `EventSourceResponse`.
"""

import asyncio
from collections.abc import AsyncIterator

import fastapi.routing
import fastapi.sse
from fastapi import FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.testclient import TestClient

from app.routers import turns

CLOUDFRONT_ORIGIN_READ_TIMEOUT_SECONDS = 60  # the origin response timeout app-stack configures
MAX_SILENCE_SECONDS = 20  # leaves room for two lost pings before CloudFront would give up


def test_the_interval_between_pings_stays_well_inside_cloudfronts_window():
    assert fastapi.sse._PING_INTERVAL <= MAX_SILENCE_SECONDS < CLOUDFRONT_ORIGIN_READ_TIMEOUT_SECONDS


def test_an_idle_stream_gets_a_ping_comment_before_its_first_event_and_the_ping_is_not_an_event(monkeypatch):
    monkeypatch.setattr(fastapi.routing, "_PING_INTERVAL", 0.05)  # the real one is 15 s; the behaviour is the same
    slow = FastAPI()

    @slow.get("/slow", response_class=EventSourceResponse)
    async def stream() -> AsyncIterator[ServerSentEvent]:
        await asyncio.sleep(1)  # the agent is thinking: nothing to say yet (20x the interval, so a loaded runner still pings)
        yield ServerSentEvent(event="done", data={"ok": True})

    with TestClient(slow).stream("GET", "/slow") as response:
        raw = b"".join(response.iter_bytes())

    assert fastapi.sse.KEEPALIVE_COMMENT in raw  # the comment line: ": ping"
    assert raw.index(fastapi.sse.KEEPALIVE_COMMENT) < raw.index(b"event: done")
    assert raw.count(b"event:") == 1  # an SSE comment is not delivered to the client as an event


def test_the_turn_endpoint_is_served_by_the_response_that_sends_the_pings():
    # The router itself, not app.routes: FastAPI wraps an included router in a lazy object that hides its routes.
    (route,) = [r for r in turns.router.routes if r.path.endswith("/{session_id}/messages") and "POST" in r.methods]
    assert route.response_class is EventSourceResponse
