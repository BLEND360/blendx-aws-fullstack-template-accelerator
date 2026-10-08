"""The real translation, run over recorded raw streams (not over an already-translated stand-in)."""

import pytest

from app.core.errors import AppError
from app.core.models import (
    ManagedToolResult,
    TextDelta,
    ToolCallReady,
    ToolCallStarted,
    TurnEnded,
)
from app.harness import fixtures
from app.harness.text_filter import MarkerFilter
from app.harness.translate import translate


def run(events):
    return list(translate(fixtures.replay(events), MarkerFilter()))


def fixture(name, invocation=0):
    return fixtures.load(name)[invocation]


def stream_of(stop_reason: str):
    return [{"messageStart": {"role": "assistant"}}, {"messageStop": {"stopReason": stop_reason}}]


def test_a_text_turn_becomes_deltas_then_the_end():
    events = run(fixture("text_only"))
    assert events == [TextDelta("Hel"), TextDelta("lo, "), TextDelta("world."), TurnEnded(needs_tools=False)]


def test_a_tool_call_with_input_in_pieces_is_started_then_ready_with_parsed_input():
    events = run(fixture("tool_call", 0))
    assert events == [
        TextDelta("Let me check. "),
        ToolCallStarted("tooluse_1", "current_time"),
        ToolCallReady("tooluse_1", "current_time", {"format": "unix"}),
        TurnEnded(needs_tools=True),
    ]


def test_the_second_invocation_of_a_tool_turn_is_the_answer():
    assert run(fixture("tool_call", 1))[-1] == TurnEnded(needs_tools=False)


def test_tool_input_that_is_not_json_is_reported_as_none_not_as_a_failure():
    events = run(fixture("bad_tool_input", 0))
    assert events[1] == ToolCallReady("tooluse_b", "current_time", None)
    assert events[-1] == TurnEnded(needs_tools=True)


def test_a_tool_the_harness_ran_itself_is_reflected_with_its_result():
    events = run(fixture("managed_tool"))
    assert events[0] == ToolCallStarted("tooluse_g", "lookup_order")
    assert events[1] == ToolCallReady("tooluse_g", "lookup_order", {"id": 7})
    assert events[2] == ManagedToolResult("tooluse_g", "lookup_order", "success", {"content": [{"json": {"state": "shipped"}}]})
    assert events[-1] == TurnEnded(needs_tools=False)  # a managed result does not ask the caller to run anything


def test_a_failed_managed_result_is_an_error_status():
    events = fixture("managed_tool")
    (result_start,) = [e for e in events if "toolResult" in e.get("contentBlockStart", {}).get("start", {})]
    result_start["contentBlockStart"]["start"]["toolResult"]["status"] = "error"
    assert [e for e in run(events) if isinstance(e, ManagedToolResult)][0].status == "error"


def test_a_marker_split_across_fragments_never_reaches_the_text():
    text = "".join(e.text for e in run(fixture("marker_split")) if isinstance(e, TextDelta))
    assert text == "Answer  and more."


def test_text_held_back_by_the_filter_is_released_before_the_end():
    events = run([{"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "a <|DS"}}}, {"messageStop": {"stopReason": "end_turn"}}])
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["a ", "<|DS"]
    assert events[-1] == TurnEnded(needs_tools=False)


def test_reasoning_metadata_and_hook_events_are_dropped():
    events = run(
        [
            {"messageStart": {"role": "assistant"}},
            {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"reasoningContent": {"text": "thinking"}}}},
            {"hookEvent": {"hookEventId": "h", "name": "x", "type": "before_invocation"}},
            {"metadata": {"usage": {}}},
            {"messageStop": {"stopReason": "end_turn"}},
        ]
    )
    assert events == [TurnEnded(needs_tools=False)]


# --- stopReason policy -------------------------------------------------------------
@pytest.mark.parametrize("reason", ["end_turn", "stop_sequence", "max_tokens", "max_output_tokens_exceeded"])
def test_these_stop_reasons_end_the_turn_normally(reason):
    assert run(stream_of(reason)) == [TurnEnded(needs_tools=False)]


def test_tool_use_asks_the_caller_to_run_tools():
    assert run(stream_of("tool_use")) == [TurnEnded(needs_tools=True)]


@pytest.mark.parametrize("reason", ["timeout_exceeded", "interrupted", "partial_turn", "malformed_model_output", "malformed_tool_use"])
def test_these_stop_reasons_are_retryable_availability_errors(reason):
    with pytest.raises(AppError) as raised:
        run(stream_of(reason))
    assert (raised.value.code, raised.value.retryable) == ("harness_unavailable", True)


@pytest.mark.parametrize(
    "reason",
    ["content_filtered", "model_context_window_exceeded", "max_iterations_exceeded", "hook_stopped", "tool_result", "something_new"],
)
def test_the_others_are_not_retryable(reason):
    with pytest.raises(AppError) as raised:
        run(stream_of(reason))
    assert (raised.value.code, raised.value.retryable) == ("harness_invalid_request", False)


# --- failures ----------------------------------------------------------------------
def test_a_failure_inside_the_stream_keeps_what_was_said_and_raises_without_the_harnesss_text():
    seen, error = [], None
    try:
        for event in translate(fixtures.replay(fixture("fails_midstream")), MarkerFilter()):
            seen.append(event)
    except AppError as exc:
        error = exc
    assert seen == [TextDelta("Working on it"), TextDelta(" and ")]
    assert error is not None
    assert (error.code, error.retryable) == ("harness_unavailable", True)
    assert "arn:aws" not in error.message and "exploded" not in error.message
    assert "exploded" in error.detail  # for the log


@pytest.mark.parametrize(
    "event,code,retryable",
    [
        ("internalServerException", "harness_unavailable", True),
        ("runtimeClientError", "harness_unavailable", True),
        ("validationException", "harness_invalid_request", False),
    ],
)
def test_each_in_stream_error_event_maps_to_the_taxonomy(event, code, retryable):
    with pytest.raises(AppError) as raised:
        run([{event: {"message": "secret text"}}])
    assert (raised.value.code, raised.value.retryable) == (code, retryable)
    assert "secret" not in raised.value.message


def test_a_stream_that_closes_without_stopping_is_an_error_not_a_silent_success():
    with pytest.raises(AppError) as raised:
        run(fixture("text_only")[:-2])  # drop messageStop and metadata
    assert (raised.value.code, raised.value.retryable) == ("harness_unavailable", True)


def test_a_connection_that_breaks_mid_stream_is_retryable_unavailability():
    from botocore.exceptions import ResponseStreamingError

    def broken():
        yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "hi"}}}
        raise ResponseStreamingError(error="connection reset")

    with pytest.raises(AppError) as raised:
        list(translate(broken(), MarkerFilter()))
    assert raised.value.code == "harness_unavailable"
