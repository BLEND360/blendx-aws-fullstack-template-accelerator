"""Invoking the configured harness: parameters, the blocking boto3 stream, and the bridge to asyncio.

Two halves, so the interesting one is testable without AWS:
  BotoInvoker      the only code that calls InvokeHarness; returns the raw event stream.
  AgentCoreHarness builds the parameters, runs a raw invoker in a worker thread and
                   translates what it yields (harness/translate.py) for the event loop.
"""

import asyncio
import contextvars
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any, Protocol

import boto3
from botocore.config import Config

from app.core.config import settings
from app.core.errors import HARNESS, AppError, classify_aws_error
from app.core.logging import get_logger
from app.core.models import HarnessEvent, HarnessMessage, HarnessRequest
from app.harness.text_filter import MarkerFilter
from app.harness.translate import translate

logger = get_logger(__name__)


class RawStream(Protocol):
    """What a raw invoker returns: AgentCore's events, plus a way to unblock a reader."""

    def __iter__(self) -> Iterator[dict[str, Any]]: ...

    def close(self) -> None: ...


class RawInvoker(Protocol):
    def invoke(self, params: dict[str, Any]) -> RawStream: ...


class _BotoStream:
    """boto3's blocking EventStream. close() ends a read another thread is blocked in."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self._stream)

    def close(self) -> None:
        self._stream.close()


def _default_client(config: Config) -> Any:
    return boto3.Session(region_name=settings.aws_region).client("bedrock-agentcore", config=config)


class BotoInvoker:
    def __init__(
        self, *, idle_timeout_seconds: int, client_factory: Callable[[Config], Any] = _default_client
    ) -> None:
        self._idle = idle_timeout_seconds
        self._factory = client_factory
        self._client: Any = None
        self._lock = threading.Lock()

    def _config(self) -> Config:
        # read_timeout is the longest silence allowed between bytes, which is what separates a slow
        # turn (events keep arriving) from a hung one. No automatic retries: InvokeHarness is not
        # idempotent, so a retry would put the user's message in the memory twice. `max_attempts`
        # counts retries after the first attempt, hence 0.
        return Config(connect_timeout=5, read_timeout=self._idle, retries={"max_attempts": 0})

    def invoke(self, params: dict[str, Any]) -> RawStream:
        with self._lock:  # one client per process, built on first use
            if self._client is None:
                self._client = self._factory(self._config())
        return _BotoStream(self._client.invoke_harness(**params)["stream"])


def _blocks(message: HarnessMessage) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if message.text is not None:
        blocks.append({"text": message.text})
    blocks.extend(
        {"toolUse": {"toolUseId": c.call_id, "name": c.name, "input": c.input}} for c in message.tool_calls
    )
    blocks.extend(
        {"toolResult": {"toolUseId": r.call_id, "status": r.status, "content": [{"json": r.content}]}}
        for r in message.tool_results
    )
    return blocks


class AgentCoreHarness:
    """Satisfies services.ports.HarnessPort."""

    def __init__(
        self,
        invoker: RawInvoker,
        *,
        harness_arn: str,
        endpoint: str,
        turn_timeout_seconds: int,
        marker_filter_factory: Callable[[], MarkerFilter] = MarkerFilter,
    ) -> None:
        self._invoker = invoker
        self._arn = harness_arn
        self._endpoint = endpoint
        self._turn_timeout = turn_timeout_seconds
        self._new_filter = marker_filter_factory

    def _params(self, request: HarnessRequest) -> dict[str, Any]:
        # Only what the server decided goes out: the harness and endpoint from configuration, the
        # session and actor from the stored record, the model and tools from the frozen config.
        params: dict[str, Any] = {
            "harnessArn": self._arn,
            "qualifier": self._endpoint,
            "runtimeSessionId": request.memory.runtime_session_id,
            "actorId": request.memory.actor_id,
            "model": {"bedrockModelConfig": {"modelId": request.model_id}},
            "messages": [{"role": m.role, "content": _blocks(m)} for m in request.messages],
            "timeoutSeconds": self._turn_timeout,
        }
        if request.tools:  # omitted, not empty: the harness keeps its own tools when we offer none
            params["tools"] = [
                {
                    "type": "inline_function",
                    "name": t.name,
                    "config": {"inlineFunction": {"description": t.description, "inputSchema": t.input_schema}},
                }
                for t in request.tools
            ]
        return params

    async def invoke(self, request: HarnessRequest) -> AsyncIterator[HarnessEvent]:
        params = self._params(request)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        cancelled = threading.Event()
        streams: list[RawStream] = []

        def put(item: tuple[str, Any]) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:  # the loop is gone (shutdown): nobody is listening
                pass

        def work() -> None:
            # Runs in the context copied below, so every log line from this thread carries
            # the request's id (the ContextVar does not cross into a raw thread by itself).
            try:
                stream = self._invoker.invoke(params)
                streams.append(stream)
                if cancelled.is_set():  # the consumer left while the call was being made
                    return
                for event in translate(stream, self._new_filter()):
                    if cancelled.is_set():
                        return
                    put(("event", event))
                put(("end", None))
            except Exception as exc:  # noqa: BLE001 - everything must reach the consumer, which re-raises it
                # A failure of the call itself (denied, throttled, not found) is a ClientError here;
                # the translator already classified anything that happened while reading the stream.
                if not cancelled.is_set():
                    put(("error", exc if isinstance(exc, AppError) else classify_aws_error(exc, dependency=HARNESS)))
            finally:
                if streams:
                    _close_quietly(streams[0])

        worker = threading.Thread(target=contextvars.copy_context().run, args=(work,), daemon=True)
        worker.start()
        try:
            while True:
                kind, value = await queue.get()
                if kind == "event":
                    yield value
                elif kind == "error":
                    raise value
                else:
                    return
        finally:
            # Reached on completion, on failure and when the client disconnects: end the worker
            # and, if it is blocked reading, close the stream under it.
            cancelled.set()
            if streams:
                _close_quietly(streams[0])


def _close_quietly(stream: RawStream) -> None:
    try:
        stream.close()
    except Exception:  # noqa: BLE001 - closing is best effort; a generator mid-run refuses and finishes by itself
        pass
