"""AgentCoreHarness and BotoInvoker, with no AWS: recorded streams, blocking streams and a stubbed boto3 client."""

import asyncio
import logging
import threading
from typing import Any

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from app.core.context import bind_request_id, reset_request_id
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.models import (
    HarnessMessage,
    HarnessRequest,
    MemoryRef,
    TextDelta,
    ToolCall,
    ToolResultBlock,
    ToolSpec,
    TurnEnded,
)
from app.harness.client import AgentCoreHarness, BotoInvoker
from app.harness.fake import ReplayInvoker

ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-1234567890"
MEMORY = MemoryRef("s-" + "a" * 32, "u-" + "b" * 32)
SPEC = ToolSpec("current_time", "Returns the time.", {"type": "object", "properties": {}})


def request(*, tools=(), messages=None) -> HarnessRequest:
    return HarnessRequest(
        memory=MEMORY,
        model_id="model-a",
        tools=tuple(tools),
        messages=tuple(messages or [HarnessMessage("user", text="hello")]),
    )


def harness(invoker, **kw) -> AgentCoreHarness:
    return AgentCoreHarness(invoker, harness_arn=ARN, endpoint="PROD", turn_timeout_seconds=900, **kw)


async def collect(h: AgentCoreHarness, req: HarnessRequest) -> list[Any]:
    return [event async for event in h.invoke(req)]


def run(h, req=None):
    return asyncio.run(collect(h, req or request()))


# --- parameters ---------------------------------------------------------------------
def test_a_turn_streams_the_translated_events_in_order():
    events = run(harness(ReplayInvoker.from_fixture("text_only")))
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Hel", "lo, ", "world."]
    assert events[-1] == TurnEnded(needs_tools=False)


def test_the_invocation_carries_only_what_the_server_decided():
    invoker = ReplayInvoker.from_fixture("text_only")
    run(harness(invoker))
    (params,) = invoker.calls
    assert params == {
        "harnessArn": ARN,
        "qualifier": "PROD",  # the configured endpoint, so another harness is only a config change
        "runtimeSessionId": MEMORY.runtime_session_id,
        "actorId": MEMORY.actor_id,
        "model": {"bedrockModelConfig": {"modelId": "model-a"}},
        "messages": [{"role": "user", "content": [{"text": "hello"}]}],
        "timeoutSeconds": 900,
    }
    assert "systemPrompt" not in params and "skills" not in params


def test_tools_are_sent_as_inline_functions_only_when_the_session_has_some():
    invoker = ReplayInvoker.from_fixture("text_only")
    run(harness(invoker), request(tools=[SPEC]))
    assert invoker.calls[0]["tools"] == [
        {
            "type": "inline_function",
            "name": "current_time",
            "config": {"inlineFunction": {"description": "Returns the time.", "inputSchema": SPEC.input_schema}},
        }
    ]


def test_a_harness_without_local_tools_still_completes_a_text_turn():
    invoker = ReplayInvoker.from_fixture("text_only")
    events = run(harness(invoker), request(tools=[]))
    assert "tools" not in invoker.calls[0]
    assert events[-1] == TurnEnded(needs_tools=False)


def test_tool_results_go_back_as_an_assistant_tool_use_then_a_user_tool_result():
    invoker = ReplayInvoker.from_fixture("text_only")
    messages = [
        HarnessMessage("assistant", tool_calls=(ToolCall("tooluse_1", "current_time", {"format": "unix"}),)),
        HarnessMessage("user", tool_results=(ToolResultBlock("tooluse_1", "success", {"time": 1}),)),
    ]
    run(harness(invoker), request(messages=messages))
    assert invoker.calls[0]["messages"] == [
        {"role": "assistant", "content": [{"toolUse": {"toolUseId": "tooluse_1", "name": "current_time", "input": {"format": "unix"}}}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": "tooluse_1", "status": "success", "content": [{"json": {"time": 1}}]}}]},
    ]


# --- failures -----------------------------------------------------------------------
class RaisingInvoker:
    def __init__(self, exc):
        self.exc = exc

    def invoke(self, params):
        raise self.exc


def test_a_call_that_is_denied_or_throttled_is_classified_not_leaked():
    exc = ClientError({"Error": {"Code": "ThrottlingException", "Message": f"{ARN} slow down"}}, "InvokeHarness")
    with pytest.raises(AppError) as raised:
        run(harness(RaisingInvoker(exc)))
    assert (raised.value.code, raised.value.retryable) == ("harness_throttled", True)
    assert ARN not in raised.value.message


class SilentInvoker:
    """The harness goes quiet: botocore's read timeout fires while iterating."""

    class _Stream:
        def __iter__(self):
            raise ReadTimeoutError(endpoint_url="https://example.invalid")
            yield  # pragma: no cover

        def close(self):
            pass

    def invoke(self, params):
        return self._Stream()


def test_silence_beyond_the_idle_limit_is_a_retryable_harness_error():
    with pytest.raises(AppError) as raised:
        run(harness(SilentInvoker()))
    assert (raised.value.code, raised.value.retryable) == ("harness_unavailable", True)


def test_the_fixture_that_fails_midstream_delivers_its_text_then_raises():
    got = []

    async def go():
        async for event in harness(ReplayInvoker.from_fixture("fails_midstream")).invoke(request()):
            got.append(event)

    with pytest.raises(AppError) as raised:
        asyncio.run(go())
    assert [e.text for e in got] == ["Working on it", " and "]
    assert raised.value.code == "harness_unavailable"


# --- threads ------------------------------------------------------------------------
class LoggingInvoker:
    """Logs from inside the worker thread, as the raw stream does when it reads."""

    class _Stream:
        def __iter__(self):
            get_logger("tests.worker").info("from_worker_thread")
            yield {"messageStop": {"stopReason": "end_turn"}}

        def close(self):
            pass

    def invoke(self, params):
        return self._Stream()


def test_log_lines_written_by_the_worker_thread_carry_the_requests_id(caplog):
    async def go():
        token = bind_request_id("rid-turn-1")
        try:
            await collect(harness(LoggingInvoker()), request())
        finally:
            reset_request_id(token)

    with caplog.at_level(logging.INFO):
        asyncio.run(go())
    record = next(r for r in caplog.records if r.getMessage() == "from_worker_thread")
    assert record.request_id == "rid-turn-1"
    assert threading.current_thread().name != record.threadName


class BlockingInvoker:
    """Yields one event, then blocks reading until closed: a harness thinking for a long time."""

    class _Stream:
        def __init__(self):
            self.release = threading.Event()
            self.finished = threading.Event()
            self.closed = False

        def __iter__(self):
            try:
                yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "partial"}}}
                self.release.wait(10)
            finally:
                self.finished.set()

        def close(self):
            self.closed = True
            self.release.set()

    def __init__(self):
        self.stream = self._Stream()

    def invoke(self, params):
        return self.stream


def test_when_the_client_disconnects_the_stream_is_closed_and_the_worker_ends():
    invoker = BlockingInvoker()

    async def go():
        agen = harness(invoker).invoke(request())
        first = await agen.__anext__()
        await agen.aclose()  # what a disconnect does to the generator
        return first

    assert asyncio.run(go()) == TextDelta("partial")
    assert invoker.stream.closed
    assert invoker.stream.finished.wait(2), "the worker thread kept reading after the consumer left"


# --- BotoInvoker --------------------------------------------------------------------
class FakeEventStream:
    def __init__(self, events):
        self.events, self.closed = events, False

    def __iter__(self):
        return iter(self.events)

    def close(self):
        self.closed = True


class FakeBoto:
    def __init__(self):
        self.calls, self.stream = [], FakeEventStream([{"messageStop": {"stopReason": "end_turn"}}])

    def invoke_harness(self, **params):
        self.calls.append(params)
        return {"stream": self.stream}


def test_the_boto_client_waits_the_idle_limit_and_never_retries():
    configs, boto = [], FakeBoto()

    def factory(config):
        configs.append(config)
        return boto

    invoker = BotoInvoker(idle_timeout_seconds=123, client_factory=factory)
    invoker.invoke({"harnessArn": ARN})
    invoker.invoke({"harnessArn": ARN})
    assert len(configs) == 1  # one client per process
    assert configs[0].read_timeout == 123
    assert configs[0].connect_timeout == 5
    assert configs[0].retries == {"max_attempts": 0}  # a retry would repeat the user's message in memory
    assert boto.calls == [{"harnessArn": ARN}, {"harnessArn": ARN}]


def test_the_boto_stream_yields_events_and_closes_the_underlying_response():
    boto = FakeBoto()
    stream = BotoInvoker(idle_timeout_seconds=1, client_factory=lambda c: boto).invoke({})
    assert list(stream) == [{"messageStop": {"stopReason": "end_turn"}}]
    stream.close()
    assert boto.stream.closed
