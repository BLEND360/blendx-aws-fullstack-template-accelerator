"""TurnService end to end over the real translator and harness adapter, fed recorded streams."""

import asyncio
import json
import logging
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from app.core.context import bind_request_id, reset_request_id
from app.core.errors import MisconfiguredError, NotFoundError, ValidationFailedError
from app.core.models import (
    Delta,
    Done,
    ErrorEvent,
    ToolFinished,
    ToolInput,
    ToolStarted,
)
from app.harness.client import AgentCoreHarness
from app.harness.fake import FakeMemory, ReplayInvoker
from app.repositories.in_memory_sessions import InMemorySessionStore
from app.services.runtime_config import Overrides
from app.services.sessions import SessionService
from app.services.turn import TurnService
from app.tools.builtin import CurrentTimeInput, make_current_time
from app.tools.registry import Tool, ToolRegistry

ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-1234567890"
NOW = datetime(2026, 10, 8, 12, 30, tzinfo=UTC)
CLOCK_TOOL = Tool("current_time", "Checking the time", "Returns the time.", CurrentTimeInput, make_current_time(lambda: NOW))


class Env:
    def __init__(self, invoker, *, tools=None, harness_arn=ARN, max_rounds=8, models=("model-a", "model-b")):
        self.store, self.invoker = InMemorySessionStore(), invoker
        self.registry = ToolRegistry([CLOCK_TOOL] if tools is None else tools)
        self.sessions = SessionService(self.store, FakeMemory(), self.registry, allowed_model_ids=list(models))
        harness = AgentCoreHarness(invoker, harness_arn=ARN, endpoint="PROD", turn_timeout_seconds=900)
        self.turns = TurnService(self.store, harness, self.registry, harness_arn=harness_arn, max_tool_rounds=max_rounds)

    def session(self, owner="alice", **overrides):
        return self.sessions.create(owner, Overrides(**overrides))

    def play(self, text="hello", owner="alice", record=None):
        record = record or self.session(owner)
        turn = self.turns.prepare(owner, record.session_id, text)

        async def collect():
            return [event async for event in self.turns.run(turn)]

        return asyncio.run(collect())


def fixture_env(name, **kw) -> Env:
    return Env(ReplayInvoker.from_fixture(name), **kw)


# --- preparing ---------------------------------------------------------------------
@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_an_empty_message_is_refused_without_calling_the_harness(text):
    env = fixture_env("text_only")
    record = env.session()
    with pytest.raises(ValidationFailedError) as raised:
        env.turns.prepare("alice", record.session_id, text)
    assert raised.value.fields[0]["location"] == "body.text"
    assert env.invoker.calls == []


def test_a_session_that_is_not_the_callers_is_not_found_and_calls_nothing():
    env = fixture_env("text_only")
    theirs = env.session("bob")
    with pytest.raises(NotFoundError):
        env.turns.prepare("alice", theirs.session_id, "hi")
    with pytest.raises(NotFoundError):
        env.turns.prepare("alice", "0" * 32, "hi")
    assert env.invoker.calls == []


def test_an_unconfigured_harness_is_a_non_retryable_misconfiguration():
    env = fixture_env("text_only", harness_arn="")
    record = env.session()
    with pytest.raises(MisconfiguredError) as raised:
        env.turns.prepare("alice", record.session_id, "hi")
    assert (raised.value.code, raised.value.retryable, raised.value.http_status) == ("harness_misconfigured", False, 500)
    assert env.invoker.calls == []


# --- a text turn --------------------------------------------------------------------
def test_a_text_turn_is_deltas_then_exactly_one_done():
    events = fixture_env("text_only").play("hello")
    assert events == [Delta("Hel"), Delta("lo, "), Delta("world."), Done()]


def test_the_harness_without_tools_of_its_own_completes_a_text_only_turn():
    env = fixture_env("text_only", tools=[])
    assert env.play()[-1] == Done()
    assert "tools" not in env.invoker.calls[0]


def test_the_turn_uses_the_sessions_frozen_configuration():
    env = fixture_env("text_only")
    record = env.session(model_id="model-b", tool_ids=[])
    env.play(record=record)
    (params,) = env.invoker.calls
    assert params["model"] == {"bedrockModelConfig": {"modelId": "model-b"}}
    assert "tools" not in params
    assert params["runtimeSessionId"] == record.memory.runtime_session_id
    assert params["messages"] == [{"role": "user", "content": [{"text": "hello"}]}]


def test_a_marker_in_the_text_never_reaches_the_events():
    events = fixture_env("marker_split").play()
    assert "".join(e.text for e in events if isinstance(e, Delta)) == "Answer  and more."
    assert events[-1] == Done()


def test_a_failure_after_text_keeps_the_text_and_ends_with_one_error_event(caplog):
    env = fixture_env("fails_midstream")
    record = env.session()

    async def go():
        token = bind_request_id("rid-failing-turn")
        try:
            turn = env.turns.prepare("alice", record.session_id, "hi")
            return [e async for e in env.turns.run(turn)]
        finally:
            reset_request_id(token)

    with caplog.at_level(logging.INFO):
        events = asyncio.run(go())

    assert events[:2] == [Delta("Working on it"), Delta(" and ")]  # nothing retracted
    assert events[2] == ErrorEvent("harness_unavailable", True, "rid-failing-turn")
    assert len(events) == 3 and not any(isinstance(e, Done) for e in events)
    failed = next(r for r in caplog.records if r.getMessage() == "turn_failed")
    assert failed.code == "harness_unavailable"
    assert "arn:aws" in failed.detail  # the original cause is in the log...
    assert "arn:aws" not in repr(events)  # ...and nowhere a client can see
    assert failed.request_id == "rid-failing-turn"


def test_an_unexpected_exception_is_an_internal_error_event_without_its_text():
    class Exploding:
        def invoke(self, request):
            raise RuntimeError("secret internals")

    env = fixture_env("text_only")
    env.turns._harness = Exploding()
    (event,) = env.play()
    assert isinstance(event, ErrorEvent) and (event.code, event.retryable) == ("internal_error", False)
    assert "secret" not in repr(event)


# --- tools --------------------------------------------------------------------------
def test_a_local_tool_is_announced_run_and_its_result_sent_back():
    env = fixture_env("tool_call")
    events = env.play("what time is it")
    assert events == [
        Delta("Let me check. "),
        ToolStarted("tooluse_1", "current_time", "Checking the time"),
        ToolInput("tooluse_1", {"format": "unix"}),
        ToolFinished("tooluse_1", "success", {"time": int(NOW.timestamp())}),
        Delta("It is "),
        Delta("late."),
        Done(),
    ]
    first, second = env.invoker.calls
    assert second["runtimeSessionId"] == first["runtimeSessionId"]  # the same conversation
    assert second["messages"] == [
        {"role": "assistant", "content": [{"toolUse": {"toolUseId": "tooluse_1", "name": "current_time", "input": {"format": "unix"}}}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": "tooluse_1", "status": "success", "content": [{"text": json.dumps({"time": int(NOW.timestamp())})}]}}]},
    ]


def test_each_calls_events_come_in_the_order_started_input_finished():
    kinds = [type(e).__name__ for e in fixture_env("tool_call").play()]
    assert kinds.index("ToolStarted") < kinds.index("ToolInput") < kinds.index("ToolFinished")


def test_the_harness_echoing_our_own_tool_result_is_not_announced_a_second_time():
    # Recorded from a deployed harness: its reply to a tool result begins by echoing that result.
    env = fixture_env("real_tool_call")
    events = env.play("what time is it")
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert len(finished) == 1 and finished[0].status == "success"  # ours, once
    assert [type(e).__name__ for e in events if not isinstance(e, Delta)] == ["ToolStarted", "ToolInput", "ToolFinished", "Done"]
    assert "".join(e.text for e in events if isinstance(e, Delta)).strip()
    assert len(env.invoker.calls) == 2


def test_a_tool_not_enabled_for_the_session_fails_for_the_model_and_the_turn_goes_on():
    env = fixture_env("tool_call")
    events = env.play(record=env.session(tool_ids=[]))
    assert ToolFinished("tooluse_1", "error", {"code": "tool_failed"}) in events
    assert events[-1] == Done()
    sent_back = env.invoker.calls[1]["messages"][1]["content"][0]["toolResult"]
    assert (sent_back["status"], sent_back["content"]) == ("error", [{"text": '{"code": "tool_failed"}'}])


def test_a_tool_that_raises_fails_for_the_model_without_its_text_and_the_turn_goes_on():
    class Boom(BaseModel):
        format: str = "iso"

    def explode(_):
        raise RuntimeError("secret internals")

    env = fixture_env("tool_call", tools=[Tool("current_time", "x", "x", Boom, explode)])
    events = env.play()
    assert ToolFinished("tooluse_1", "error", {"code": "tool_failed"}) in events
    assert events[-1] == Done()
    assert "secret" not in repr(events)


def test_tool_input_that_was_not_json_is_a_tool_failure_not_a_dead_turn():
    env = fixture_env("bad_tool_input")
    events = env.play()
    assert ToolInput("tooluse_b", {}) in events
    assert ToolFinished("tooluse_b", "error", {"code": "tool_failed"}) in events
    assert events[-1] == Done() and Delta("Sorry about that.") in events


def test_a_tool_the_harness_ran_itself_is_reflected_and_not_run_again():
    env = fixture_env("managed_tool")
    events = env.play()
    assert [type(e).__name__ for e in events] == ["ToolStarted", "ToolInput", "ToolFinished", "Delta", "Done"]
    assert events[0].label == "lookup_order"  # not ours: the name is the label
    assert len(env.invoker.calls) == 1  # nothing to send back


def test_a_turn_that_keeps_asking_for_tools_stops_at_the_round_limit_with_an_error_event():
    (round_one,) = ReplayInvoker.from_fixture("tool_call")._streams[:1]
    env = Env(ReplayInvoker([round_one] * 10), max_rounds=2)
    events = env.play()
    assert events[-1] == ErrorEvent("tool_failed", False, None)
    assert len(env.invoker.calls) == 3  # the first invocation plus two rounds, then it gives up
    assert not any(isinstance(e, Done) for e in events)
