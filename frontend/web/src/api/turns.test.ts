import { ApiError } from "./client";
import type { TurnEvent } from "./events";
import { session } from "./session";
import { streamTurn } from "./turns";
import { hangingResponse, pieces, sseBlock, SSE_PING, streamResponse } from "../test/sse";

const fetchMock = vi.fn<typeof fetch>();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  session.onUnauthorized(null);
});

const TEXT = sseBlock("delta", { text: "wörld ✓ " }) + SSE_PING + sseBlock("delta", { text: "ok" }) + sseBlock("done", {});

async function run(signal = new AbortController().signal) {
  const events: TurnEvent[] = [];
  const end = await streamTurn("s1", "hello", signal, (e) => events.push(e));
  return { end, events };
}

test("posts the message to the session's messages route and delivers the events in order", async () => {
  fetchMock.mockResolvedValue(streamResponse([TEXT]));
  const { end, events } = await run();
  expect(end).toBe("done");
  expect(events.map((e) => e.type)).toEqual(["delta", "delta", "done"]);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/v1/sessions/s1/messages");
  expect(init?.method).toBe("POST");
  expect(init?.body).toBe('{"text":"hello"}');
});

test("the same events however the body is chunked, including a character cut in half", async () => {
  const reference = (await (async () => {
    fetchMock.mockResolvedValue(streamResponse([TEXT]));
    return run();
  })()).events;

  const bytes = new TextEncoder().encode(TEXT);
  for (let cut = 0; cut <= bytes.length; cut++) {
    fetchMock.mockResolvedValue(streamResponse([bytes.slice(0, cut), bytes.slice(cut)])); // cuts "ö" and "✓" mid-character
    expect((await run()).events).toEqual(reference);
  }
  fetchMock.mockResolvedValue(streamResponse(pieces(TEXT, 1)));
  expect((await run()).events).toEqual(reference);
});

test("an error event ends the turn as an error and is delivered", async () => {
  fetchMock.mockResolvedValue(
    streamResponse([sseBlock("delta", { text: "Working" }), sseBlock("error", { code: "harness_unavailable", retryable: true, requestId: "rid-1" })]),
  );
  const { end, events } = await run();
  expect(end).toBe("error");
  expect(events.at(-1)).toEqual({ type: "error", code: "harness_unavailable", retryable: true, requestId: "rid-1" });
});

test("a body that closes without a terminal event is interrupted, and what arrived was delivered", async () => {
  fetchMock.mockResolvedValue(streamResponse([sseBlock("delta", { text: "partial" })]));
  const { end, events } = await run();
  expect(end).toBe("interrupted");
  expect(events).toEqual([{ type: "delta", text: "partial" }]);
});

test("an event cut off by the close is not delivered", async () => {
  fetchMock.mockResolvedValue(streamResponse([sseBlock("delta", { text: "a" }), 'event: delta\ndata: {"text": "b"']));
  const { end, events } = await run();
  expect(end).toBe("interrupted");
  expect(events).toEqual([{ type: "delta", text: "a" }]);
});

test("nothing after the terminal event is delivered", async () => {
  fetchMock.mockResolvedValue(streamResponse([sseBlock("done", {}) + sseBlock("delta", { text: "late" })]));
  const { end, events } = await run();
  expect(end).toBe("done");
  expect(events).toEqual([{ type: "done" }]);
});

test("a refusal before the stream is an ApiError and delivers no events", async () => {
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify({ error: { code: "validation_error", message: "The request is not valid.", retryable: false, requestId: "rid-v" } }), {
      status: 422,
      headers: { "Content-Type": "application/json" },
    }),
  );
  const events: TurnEvent[] = [];
  const error = await streamTurn("s1", " ", new AbortController().signal, (e) => events.push(e)).catch((e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ status: 422, code: "validation_error", requestId: "rid-v" });
  expect(events).toEqual([]);
});

test("a 401 reaches the session handler like for any other request", async () => {
  const handler = vi.fn();
  session.onUnauthorized(handler);
  fetchMock.mockResolvedValue(new Response(JSON.stringify({ error: { code: "auth_invalid_token", message: "Sign in again." } }), { status: 401 }));
  await streamTurn("s1", "hi", new AbortController().signal, () => {}).catch(() => {});
  expect(handler).toHaveBeenCalledOnce();
});

test("aborting while the stream is open rejects with the abort", async () => {
  const controller = new AbortController();
  fetchMock.mockImplementation((_url, init) => Promise.resolve(hangingResponse(sseBlock("delta", { text: "a" }), init?.signal)));
  const events: TurnEvent[] = [];
  const pending = streamTurn("s1", "hi", controller.signal, (e) => events.push(e));
  await vi.waitFor(() => expect(events).toHaveLength(1));
  controller.abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  expect(events).toEqual([{ type: "delta", text: "a" }]);
});

test("a session id is encoded into the path", async () => {
  fetchMock.mockResolvedValue(streamResponse([sseBlock("done", {})]));
  await streamTurn("a/b", "hi", new AbortController().signal, () => {});
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/sessions/a%2Fb/messages");
});
