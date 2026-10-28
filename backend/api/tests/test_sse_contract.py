"""The SSE wire contract: the bytes the turn endpoint emits must equal contract/sse-turns.json, the fixture
the frontend parser and reducer are tested against. The only thing the two apps share is that file."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.context import REQUEST_ID_HEADER
from app.core.models import TURN_EVENT_NAMES
from app.harness.client import AgentCoreHarness
from app.harness.fake import ReplayInvoker
from app.main import app
from app.routers import dependencies as deps
from app.services.turn import TurnService
from app.tools.builtin import CurrentTimeInput, make_current_time
from app.tools.registry import Tool, ToolRegistry
from tests.api_stack import ARN, install, uninstall
from tests.test_turns_api import send

CONTRACT = json.loads((Path(__file__).resolve().parents[3] / "contract" / "sse-turns.json").read_text(encoding="utf-8"))
FIXED_CLOCK = datetime.fromtimestamp(1700000000, UTC)
CLOCK_TOOL = Tool("current_time", "Checking the time", "Returns the time.", CurrentTimeInput, make_current_time(lambda: FIXED_CLOCK))


@pytest.fixture
def stack_for():
    def make(harness_fixture: str):
        stack = install(ReplayInvoker.from_fixture(harness_fixture))
        harness = AgentCoreHarness(stack.invoker, harness_arn=ARN, endpoint="PROD", turn_timeout_seconds=900)
        turns = TurnService(stack.store, harness, ToolRegistry([CLOCK_TOOL]), harness_arn=ARN, max_tool_rounds=8)
        app.dependency_overrides[deps.turn_service] = lambda: turns
        return stack

    yield make
    uninstall()


@pytest.mark.parametrize("turn", CONTRACT["turns"], ids=lambda t: t["name"])
def test_the_endpoint_emits_the_fixture_bytes(stack_for, turn):
    headers = {REQUEST_ID_HEADER: turn["requestId"]} if turn["requestId"] else {}
    response = send(stack_for(turn["harnessFixture"]), headers=headers)
    assert response.status_code == 200
    assert response.text == turn["wire"]
    if "event: error" in turn["wire"]:  # the failed turn must not leak AWS detail
        assert "arn:aws" not in response.text and "exploded" not in response.text


def test_the_vocabulary_is_closed_and_every_name_is_used_by_a_turn():
    assert sorted(TURN_EVENT_NAMES.values()) == sorted(CONTRACT["vocabulary"])
    used = {line[len("event: "):] for turn in CONTRACT["turns"] for line in turn["wire"].split("\n") if line.startswith("event: ")}
    assert used == set(CONTRACT["vocabulary"])
