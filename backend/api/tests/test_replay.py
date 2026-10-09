"""Replay mode: recorded answers through the real translator, with no AWS and a history that works."""

import asyncio
import logging
import time

import boto3
import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.core.models import (
    HarnessMessage,
    HarnessRequest,
    MemoryRef,
    TextDelta,
    ToolCall,
    ToolCallReady,
    ToolCallStarted,
    ToolResultBlock,
    TurnEnded,
)
from app.harness.client import AgentCoreHarness
from app.harness.fake import FakeMemory
from app.harness.memory import AgentCoreMemory
from app.harness.replay import ReplayHarness
from app.main import app
from app.routers import dependencies as deps
from tests.test_turns_api import parse_sse

MEM = MemoryRef("s-" + "a" * 32, "u-" + "b" * 32)


def ask(text: str) -> HarnessRequest:
    return HarnessRequest(MEM, "model-a", (), (HarnessMessage("user", text=text),))


def play(harness: ReplayHarness, request: HarnessRequest) -> list:
    async def go():
        return [event async for event in harness.invoke(request)]

    return asyncio.run(go())


@pytest.fixture
def memory():
    return FakeMemory()


@pytest.fixture
def harness(memory):
    return ReplayHarness(memory, event_delay_seconds=0)


@pytest.fixture(autouse=True)
def no_aws(monkeypatch):
    """Replay must never reach AWS: any attempt to build a boto3 session fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("replay mode touched boto3")

    monkeypatch.setattr(boto3, "Session", refuse)


# ----------------------------------------- the harness -----------------------------------------
def test_an_ordinary_message_plays_the_recorded_text_turn(harness):
    events = play(harness, ask("What is the weather like?"))
    assert "".join(e.text for e in events if isinstance(e, TextDelta)).strip()
    assert not any(isinstance(e, ToolCallStarted) for e in events)
    assert events[-1] == TurnEnded(needs_tools=False)


@pytest.mark.parametrize("text", ["use the tool", "TOOL", "Please run a ToOl for me", "what tools do you have"])
def test_the_word_tool_in_any_capitalization_plays_the_tool_turn(harness, text):
    events = play(harness, ask(text))
    assert any(isinstance(e, ToolCallStarted) for e in events)
    assert any(isinstance(e, ToolCallReady) and e.input == {"format": "iso"} for e in events)
    assert events[-1] == TurnEnded(needs_tools=True)


def test_the_answer_to_a_tool_result_plays_the_recorded_second_round(harness):
    request = HarnessRequest(
        MEM,
        "model-a",
        (),
        (
            HarnessMessage("user", text="use the tool"),
            HarnessMessage("assistant", tool_calls=(ToolCall("tooluse_x", "current_time", {"format": "iso"}),)),
            HarnessMessage("user", tool_results=(ToolResultBlock("tooluse_x", "success", {"time": "now"}),)),
        ),
    )
    events = play(harness, request)
    assert "".join(e.text for e in events if isinstance(e, TextDelta)).strip()
    assert events[-1] == TurnEnded(needs_tools=False)


def test_a_text_turn_leaves_the_question_and_the_answer_in_the_history(harness, memory):
    events = play(harness, ask("hello there"))
    answer = "".join(e.text for e in events if isinstance(e, TextDelta))
    stored = list(memory.list_events(MEM))
    assert [(e.role, e.text) for e in stored] == [("USER", "hello there"), ("ASSISTANT", answer)]


def test_a_tool_turn_records_the_question_once_and_the_final_answer_once(harness, memory):
    play(harness, ask("use the tool"))
    play(
        harness,
        HarnessRequest(
            MEM,
            "model-a",
            (),
            (
                HarnessMessage("user", text="use the tool"),
                HarnessMessage("assistant", tool_calls=(ToolCall("t", "current_time", {}),)),
                HarnessMessage("user", tool_results=(ToolResultBlock("t", "success", {}),)),
            ),
        ),
    )
    assert [e.role for e in memory.list_events(MEM)] == ["USER", "ASSISTANT"]


def test_it_pauses_between_events_so_the_streaming_can_be_seen():
    slow = ReplayHarness(FakeMemory(), event_delay_seconds=0.03)
    started = time.monotonic()
    events = play(slow, ask("hi"))
    assert time.monotonic() - started >= 0.03 * (len(events) - 2)  # no pause after the last event


def test_it_plays_nothing_against_aws(harness):
    play(harness, ask("anything"))  # the autouse fixture fails the test if boto3 is touched


# ----------------------------------------- the settings -----------------------------------------
def test_replay_is_off_by_default(monkeypatch):
    monkeypatch.delenv("HARNESS_REPLAY", raising=False)
    loaded = config.load_settings()
    assert (loaded.harness_replay, loaded.replay_enabled) == (False, False)


def test_replay_is_on_when_asked_for_outside_a_deployed_task(monkeypatch):
    monkeypatch.setenv("HARNESS_REPLAY", "true")
    assert config.load_settings().replay_enabled is True


def test_a_deployed_task_ignores_the_setting(monkeypatch):
    monkeypatch.setenv("HARNESS_REPLAY", "true")
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI_V4", "http://169.254.170.2/v4/abc")
    loaded = config.load_settings()
    assert (loaded.harness_replay, loaded.replay_enabled) == (True, False)


# ----------------------------------------- through the API -----------------------------------------
CACHED = ("session_store", "replay_memory", "harness_memory", "harness", "turn_service", "session_service", "history_service")


def reset_wiring():
    for name in CACHED:
        getattr(deps, name).cache_clear()


@pytest.fixture
def replay_app(monkeypatch):
    monkeypatch.setattr(deps.settings, "harness_replay", True)
    monkeypatch.setattr(deps.settings, "harness_replay_delay_seconds", 0)
    monkeypatch.setattr(deps.settings, "harness_arn", "")  # no harness configured at all
    monkeypatch.setattr(deps.settings, "local_auth_bypass", True)
    reset_wiring()
    yield TestClient(app, raise_server_exceptions=False)
    reset_wiring()


def test_a_whole_conversation_works_over_http_with_no_harness_and_no_aws(replay_app):
    created = replay_app.post("/api/v1/sessions", json={})
    assert created.status_code == 201
    sid = created.json()["id"]

    text = replay_app.post(f"/api/v1/sessions/{sid}/messages", json={"text": "hello"})
    assert text.status_code == 200
    names = [n for n, _ in parse_sse(text.text)]
    assert names[-1] == "done" and set(names) == {"delta", "done"}

    tool = parse_sse(replay_app.post(f"/api/v1/sessions/{sid}/messages", json={"text": "use the tool"}).text)
    assert [n for n, _ in tool if n.startswith("tool_")] == ["tool_started", "tool_input", "tool_finished"]
    finished = next(d for n, d in tool if n == "tool_finished")
    assert finished["status"] == "success" and "time" in finished["result"]  # the local tool really ran
    assert tool[-1][0] == "done"
    assert sum(1 for n, _ in tool if n == "tool_finished") == 1  # the recorded echo was not announced again

    history = replay_app.get(f"/api/v1/sessions/{sid}/messages").json()["messages"]
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
    assert history[0]["text"] == "hello" and history[2]["text"] == "use the tool"

    assert replay_app.delete(f"/api/v1/sessions/{sid}").status_code == 204
    assert replay_app.get("/api/v1/sessions").json() == {"sessions": []}


def test_the_client_configuration_says_it_is_a_demonstration(replay_app):
    assert replay_app.get("/api/v1/configuration").json()["replayMode"] is True


def test_starting_the_app_warns_that_replay_is_on(replay_app, caplog):
    with caplog.at_level(logging.WARNING):
        with TestClient(app):
            pass
    assert any(r.getMessage() == "harness_replay_enabled" for r in caplog.records)


def test_in_a_deployed_task_the_setting_is_ignored_with_a_warning(monkeypatch, caplog):
    monkeypatch.setattr(deps.settings, "harness_replay", True)
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI_V4", "http://169.254.170.2/v4/abc")
    reset_wiring()
    try:
        with caplog.at_level(logging.WARNING):
            with TestClient(app):
                pass
        messages = [r.getMessage() for r in caplog.records]
        assert "harness_replay_ignored" in messages and "harness_replay_enabled" not in messages
        assert isinstance(deps.harness(), AgentCoreHarness)  # the real one
        assert isinstance(deps.harness_memory(), AgentCoreMemory)
    finally:
        reset_wiring()


def test_without_the_setting_nothing_changes(monkeypatch):
    monkeypatch.setattr(deps.settings, "harness_replay", False)
    reset_wiring()
    try:
        assert isinstance(deps.harness(), AgentCoreHarness)
        assert isinstance(deps.harness_memory(), AgentCoreMemory)
        assert not isinstance(deps.harness(), ReplayHarness)
    finally:
        reset_wiring()
