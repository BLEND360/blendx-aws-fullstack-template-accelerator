"""The stand-in harness: a text turn, a tool turn and a failure, replayed through the real translator."""

import pytest

from app.core.errors import AppError, UnavailableError
from app.core.models import MemoryRef, TextDelta, ToolCallReady, TurnEnded
from app.harness.fake import FakeMemory, ReplayInvoker
from app.harness.text_filter import MarkerFilter
from app.harness.translate import translate


def play(invoker: ReplayInvoker, params=None):
    return list(translate(invoker.invoke(params or {}), MarkerFilter()))


def test_a_text_turn_is_replayed():
    events = play(ReplayInvoker.from_fixture("text_only"))
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Hello, world."
    assert events[-1] == TurnEnded(needs_tools=False)


def test_a_tool_turn_is_replayed_over_two_invocations_and_records_what_it_was_given():
    invoker = ReplayInvoker.from_fixture("tool_call")
    first = play(invoker, {"messages": "first"})
    second = play(invoker, {"messages": "second"})
    assert any(isinstance(e, ToolCallReady) for e in first) and first[-1] == TurnEnded(needs_tools=True)
    assert second[-1] == TurnEnded(needs_tools=False)
    assert invoker.calls == [{"messages": "first"}, {"messages": "second"}]


def test_a_failure_turn_says_something_then_fails_like_botocore_would():
    seen = []
    with pytest.raises(AppError) as raised:
        for event in translate(ReplayInvoker.from_fixture("fails_midstream").invoke({}), MarkerFilter()):
            seen.append(event)
    assert seen and all(isinstance(e, TextDelta) for e in seen)
    assert raised.value.code == "harness_unavailable"


def test_asking_for_more_invocations_than_were_recorded_fails_loudly():
    invoker = ReplayInvoker.from_fixture("text_only")
    play(invoker)
    with pytest.raises(AssertionError):
        invoker.invoke({})


# --- FakeMemory ----------------------------------------------------------------------
MEM = MemoryRef("s-" + "a" * 32, "u-" + "b" * 32)


def test_fake_memory_lists_what_was_added_and_purges_it():
    memory = FakeMemory()
    memory.add(MEM, "USER", "hi", "2026-10-08T10:00:00Z")
    memory.add(MEM, "ASSISTANT", "hello", "2026-10-08T10:00:01Z")
    assert [e.text for e in memory.list_events(MEM)] == ["hi", "hello"]
    memory.purge(MEM)
    assert list(memory.list_events(MEM)) == []


def test_a_failing_purge_removes_part_and_a_retry_finishes_it():
    memory = FakeMemory()
    for i in range(4):
        memory.add(MEM, "USER", f"m{i}", f"2026-10-08T10:00:0{i}Z")
    memory.purge_error = UnavailableError("down", dependency="memory")
    with pytest.raises(UnavailableError):
        memory.purge(MEM)
    assert 0 < len(memory.events[MEM.runtime_session_id]) < 4
    memory.purge_error = None
    memory.purge(MEM)
    assert list(memory.list_events(MEM)) == []
    assert (memory.purge_calls, memory.list_calls) == (2, 1)
