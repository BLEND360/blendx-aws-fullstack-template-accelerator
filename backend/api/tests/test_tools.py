from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from app.tools import builtin
from app.tools.registry import MAX_PUBLIC_RESULT_BYTES, Tool, ToolRegistry

NOW = datetime(2026, 10, 8, 12, 30, tzinfo=UTC)
SECRET = "arn:aws:iam::123456789012:role/secret-role"


class Box(BaseModel):
    n: int = 1


def tool(handler, tool_id="t") -> Tool:
    return Tool(id=tool_id, label="A tool", description="Does a thing.", input_model=Box, handler=handler)


def registry_with(handler) -> ToolRegistry:
    return ToolRegistry([tool(handler)])


# --- the example tool ---------------------------------------------------------------
def test_the_example_tool_is_registered_and_runs():
    assert "current_time" in builtin.registry.ids()
    assert builtin.registry.label("current_time")


@pytest.mark.parametrize("raw,expected", [({}, NOW.isoformat()), ({"format": "iso"}, NOW.isoformat()), ({"format": "unix"}, int(NOW.timestamp()))])
def test_current_time_with_a_fixed_clock(raw, expected):
    registry = ToolRegistry(
        [Tool("current_time", "x", "x", builtin.CurrentTimeInput, builtin.make_current_time(lambda: NOW))]
    )
    outcome = registry.run("current_time", raw)
    assert outcome.status == "success"
    assert outcome.result == {"time": expected}
    assert outcome.public_result == outcome.result


def test_the_spec_sent_to_the_harness_comes_from_the_input_model():
    (spec,) = builtin.registry.specs_for(["current_time"])
    assert spec.name == "current_time"
    assert spec.description
    assert spec.input_schema["properties"]["format"]["enum"] == ["iso", "unix"]


def test_specs_skip_ids_that_are_not_registered():
    assert builtin.registry.specs_for(["ghost"]) == ()


# --- failures never raise and never leak ----------------------------------------------
def assert_failed(outcome):
    assert outcome.status == "error"
    assert outcome.result == {"code": "tool_failed"}
    assert outcome.public_result == {"code": "tool_failed"}


def test_an_unknown_tool_is_a_failed_outcome():
    assert_failed(ToolRegistry([]).run("ghost", {}))


def test_input_that_was_not_json_is_a_failed_outcome():
    assert_failed(registry_with(lambda a: {}).run("t", None))


def test_input_that_does_not_validate_is_a_failed_outcome():
    assert_failed(registry_with(lambda a: {}).run("t", {"n": "not a number"}))


def test_a_handler_that_raises_is_a_failed_outcome_without_its_text():
    def boom(_):
        raise RuntimeError(SECRET)

    outcome = registry_with(boom).run("t", {})
    assert_failed(outcome)
    assert SECRET not in str(outcome)


def test_a_result_that_cannot_be_serialized_is_a_failed_outcome():
    assert_failed(registry_with(lambda a: {"x": object()}).run("t", {}))


def test_a_model_result_is_dumped_to_plain_data():
    assert registry_with(lambda a: Box(n=7)).run("t", {}).result == {"n": 7}


def test_a_large_result_reaches_the_harness_whole_but_the_browser_gets_a_marker():
    big = {"blob": "x" * (MAX_PUBLIC_RESULT_BYTES + 1)}
    outcome = registry_with(lambda a: big).run("t", {})
    assert outcome.result == big
    assert outcome.public_result == {"truncated": True}


# --- declaring tools -------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["", "has space", "a" * 65, "dots.not.ok"])
def test_an_id_the_harness_would_reject_fails_at_startup(bad):
    with pytest.raises(ValueError):
        ToolRegistry([tool(lambda a: {}, bad)])


def test_a_duplicate_id_fails_at_startup():
    with pytest.raises(ValueError):
        ToolRegistry([tool(lambda a: {}), tool(lambda a: {})])
