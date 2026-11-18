import { act, renderHook, waitFor } from "@testing-library/react";
import { ApiError } from "../../api/client";
import type { TurnEvent } from "../../api/events";
import { streamTurn } from "../../api/turns";
import type { TurnEnd } from "../../api/turns";
import { MAX_MESSAGE_CHARS } from "./chatState";
import { useChat } from "./useChat";

vi.mock("../../api/turns", () => ({ streamTurn: vi.fn() }));
const stream = vi.mocked(streamTurn);

type Script = (emit: (e: TurnEvent) => void, signal: AbortSignal) => Promise<TurnEnd>;
const script = (fn: Script) =>
  stream.mockImplementationOnce((_id, _text, signal, onEvent) => fn(onEvent, signal));

const apiError = (status: number, code: string, retryable = false) =>
  new ApiError({ status, code, message: `${code} happened.`, retryable, requestId: "rid-x" });

function setup(initial = []) {
  const onSessionGone = vi.fn();
  const hook = renderHook(() => useChat("s1", initial, onSessionGone));
  return { ...hook, onSessionGone };
}

beforeEach(() => stream.mockReset());

test("a turn shows the message at once, streams the answer and ends idle", async () => {
  script(async (emit) => {
    emit({ type: "delta", text: "Hel" });
    emit({ type: "delta", text: "lo" });
    emit({ type: "done" });
    return "done";
  });
  const { result } = setup();
  act(() => result.current.send("hi"));
  expect(result.current.state.items[0]).toMatchObject({ kind: "user", text: "hi" }); // before any event
  await waitFor(() => expect(result.current.state.turn.phase).toBe("idle"));
  expect(result.current.state.items.map((i) => i.kind)).toEqual(["user", "assistant"]);
  expect(result.current.state.items[1]).toMatchObject({ text: "Hello", complete: true });
  expect(stream).toHaveBeenCalledWith("s1", "hi", expect.any(AbortSignal), expect.any(Function));
});

test("a message cannot be sent while another turn is running", async () => {
  let release: () => void = () => {};
  script((emit) => new Promise<TurnEnd>((resolve) => (release = () => { emit({ type: "done" }); resolve("done"); })));
  const { result } = setup();
  act(() => result.current.send("first"));
  act(() => result.current.send("second"));
  expect(stream).toHaveBeenCalledOnce();
  expect(result.current.state.items.filter((i) => i.kind === "user")).toHaveLength(1);
  act(() => release());
  await waitFor(() => expect(result.current.state.turn.phase).toBe("idle"));
});

test.each(["", "   ", "\n\t"])("an empty message (%j) is not sent", (text) => {
  const { result } = setup();
  act(() => result.current.send(text));
  expect(stream).not.toHaveBeenCalled();
  expect(result.current.state.items).toEqual([]);
});

test("a message over the limit is not sent, and one at the limit is", async () => {
  const { result } = setup();
  act(() => result.current.send("x".repeat(MAX_MESSAGE_CHARS + 1)));
  expect(stream).not.toHaveBeenCalled();
  script(async (emit) => (emit({ type: "done" }), "done"));
  act(() => result.current.send("x".repeat(MAX_MESSAGE_CHARS)));
  await waitFor(() => expect(result.current.state.turn.phase).toBe("idle"));
  expect(stream).toHaveBeenCalledOnce();
});

test("a refusal before the stream fails the turn with the API's own error", async () => {
  stream.mockRejectedValueOnce(apiError(422, "validation_error"));
  const { result } = setup();
  act(() => result.current.send("hi"));
  await waitFor(() => expect(result.current.state.turn.phase).toBe("failed"));
  expect(result.current.state.turn).toMatchObject({ failure: { kind: "api", error: { code: "validation_error", requestId: "rid-x" } } });
});

test("a 404 means the conversation is gone: it is reported and forgotten", async () => {
  stream.mockRejectedValueOnce(apiError(404, "not_found"));
  const { result, onSessionGone } = setup();
  act(() => result.current.send("hi"));
  await waitFor(() => expect(result.current.state.turn).toEqual({ phase: "failed", failure: { kind: "sessionGone" } }));
  expect(onSessionGone).toHaveBeenCalledOnce();
});

test("a body that ends without a final event is an interruption that keeps the text", async () => {
  script(async (emit) => (emit({ type: "delta", text: "partial" }), "interrupted"));
  const { result } = setup();
  act(() => result.current.send("hi"));
  await waitFor(() => expect(result.current.state.turn).toEqual({ phase: "failed", failure: { kind: "interrupted" } }));
  expect(result.current.state.items.at(-1)).toMatchObject({ text: "partial" });
});

test("an error event keeps what arrived and carries code, retryability and request id", async () => {
  script(async (emit) => {
    emit({ type: "delta", text: "so far" });
    emit({ type: "error", code: "harness_unavailable", retryable: true, requestId: "rid-7" });
    return "error";
  });
  const { result } = setup();
  act(() => result.current.send("hi"));
  await waitFor(() => expect(result.current.state.turn.phase).toBe("failed"));
  expect(result.current.state.turn).toMatchObject({ failure: { kind: "stream", code: "harness_unavailable", retryable: true, requestId: "rid-7" } });
  expect(result.current.state.items.at(-1)).toMatchObject({ text: "so far" });
});

test("retrying sends the same message again, shows it once, and replaces the failed attempt", async () => {
  script(async (emit) => {
    emit({ type: "delta", text: "broken" });
    emit({ type: "error", code: "harness_unavailable", retryable: true, requestId: null });
    return "error";
  });
  script(async (emit) => (emit({ type: "delta", text: "fixed" }), emit({ type: "done" }), "done"));
  const { result } = setup();
  act(() => result.current.send("question"));
  await waitFor(() => expect(result.current.state.turn.phase).toBe("failed"));

  act(() => result.current.retry());
  await waitFor(() => expect(result.current.state.turn.phase).toBe("idle"));
  expect(stream.mock.calls.map((c) => c[1])).toEqual(["question", "question"]);
  expect(result.current.state.items.map((i) => (i.kind === "user" || i.kind === "assistant" ? i.text : i.callId))).toEqual(["question", "fixed"]);
});

test("retry does nothing when no turn has failed", () => {
  const { result } = setup();
  act(() => result.current.retry());
  expect(stream).not.toHaveBeenCalled();
});

test("leaving the page aborts the turn so the stream is not left open", async () => {
  let seen: AbortSignal | undefined;
  script((_emit, signal) => ((seen = signal), new Promise<TurnEnd>(() => {})));
  const { result, unmount } = setup();
  act(() => result.current.send("hi"));
  await waitFor(() => expect(seen).toBeDefined());
  expect(seen?.aborted).toBe(false);
  unmount();
  expect(seen?.aborted).toBe(true);
});

test("an aborted turn does not report a failure", async () => {
  script((_emit, signal) => new Promise<TurnEnd>((_res, reject) => signal.addEventListener("abort", () => reject(new DOMException("a", "AbortError")))));
  const { result, unmount } = setup();
  act(() => result.current.send("hi"));
  unmount();
  await new Promise((r) => setTimeout(r, 0));
  expect(result.current.state.turn.phase).toBe("streaming"); // untouched by the abort
});
