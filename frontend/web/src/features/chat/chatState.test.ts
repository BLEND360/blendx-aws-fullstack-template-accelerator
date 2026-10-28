import { ApiError } from "../../api/client";
import type { TurnEvent } from "../../api/events";
import { chatReducer, emptyChat } from "./chatState";
import type { ChatAction, ChatState } from "./chatState";

const run = (state: ChatState, ...actions: ChatAction[]) => actions.reduce(chatReducer, state);
const ev = (event: TurnEvent): ChatAction => ({ type: "event", event });
const sent = (text = "hello"): ChatAction => ({ type: "userSent", id: "u1", text });
const delta = (text: string) => ev({ type: "delta", text });

test("sending shows the message at once and starts a turn", () => {
  const state = run(emptyChat(), sent("hi there"));
  expect(state.items).toEqual([{ kind: "user", id: "u1", text: "hi there" }]);
  expect(state.turn).toEqual({ phase: "streaming" });
  expect(state.pendingText).toBe("hi there");
});

test("text deltas grow one assistant message, which done completes", () => {
  const state = run(emptyChat(), sent(), delta("Hel"), delta("lo"), ev({ type: "done" }));
  expect(state.items.at(-1)).toMatchObject({ kind: "assistant", text: "Hello", complete: true });
  expect(state.items).toHaveLength(2);
  expect(state.turn).toEqual({ phase: "idle" });
});

test("a tool card between two stretches of text splits them into two messages, in order", () => {
  const state = run(
    emptyChat(),
    sent(),
    delta("Let me check. "),
    ev({ type: "tool_started", callId: "t1", toolId: "current_time", label: "Checking the time" }),
    ev({ type: "tool_input", callId: "t1", input: { format: "iso" } }),
    ev({ type: "tool_finished", callId: "t1", status: "success", result: { time: "now" } }),
    delta("It is late."),
    ev({ type: "done" }),
  );
  expect(state.items.map((i) => i.kind)).toEqual(["user", "assistant", "tool", "assistant"]);
  expect(state.items[1]).toMatchObject({ text: "Let me check. ", complete: true }); // closed when the tool began
  expect(state.items[2]).toEqual({ kind: "tool", callId: "t1", label: "Checking the time", status: "success", input: { format: "iso" }, result: { time: "now" } });
  expect(state.items[3]).toMatchObject({ text: "It is late.", complete: true });
});

test("a tool is running from its start until it finishes, and a failure is an error status", () => {
  const started = run(emptyChat(), sent(), ev({ type: "tool_started", callId: "t1", toolId: "x", label: "Doing x" }));
  expect(started.items.at(-1)).toMatchObject({ kind: "tool", status: "running" });
  const failed = run(started, ev({ type: "tool_finished", callId: "t1", status: "error", result: { code: "tool_failed" } }));
  expect(failed.items.at(-1)).toMatchObject({ status: "error", result: { code: "tool_failed" } });
});

test("two tools in one turn keep their own data, in order", () => {
  const state = run(
    emptyChat(),
    sent(),
    ev({ type: "tool_started", callId: "a", toolId: "x", label: "First" }),
    ev({ type: "tool_started", callId: "b", toolId: "y", label: "Second" }),
    ev({ type: "tool_input", callId: "b", input: { n: 2 } }),
    ev({ type: "tool_finished", callId: "a", status: "success", result: 1 }),
  );
  const tools = state.items.filter((i) => i.kind === "tool");
  expect(tools.map((t) => (t.kind === "tool" ? [t.callId, t.status, t.input, t.result] : null))).toEqual([
    ["a", "success", undefined, 1],
    ["b", "running", { n: 2 }, undefined],
  ]);
});

test("an event about a tool that never started is ignored, and a repeated start does not add a second card", () => {
  const state = run(
    emptyChat(),
    sent(),
    ev({ type: "tool_input", callId: "ghost", input: {} }),
    ev({ type: "tool_finished", callId: "ghost", status: "success", result: {} }),
    ev({ type: "tool_started", callId: "t1", toolId: "x", label: "X" }),
    ev({ type: "tool_started", callId: "t1", toolId: "x", label: "X" }),
  );
  expect(state.items.filter((i) => i.kind === "tool")).toHaveLength(1);
});

test("an error event keeps everything received and records why", () => {
  const state = run(emptyChat(), sent(), delta("Working"), ev({ type: "error", code: "harness_unavailable", retryable: true, requestId: "rid-1" }));
  expect(state.items.at(-1)).toMatchObject({ kind: "assistant", text: "Working", complete: true });
  expect(state.turn).toEqual({ phase: "failed", failure: { kind: "stream", code: "harness_unavailable", retryable: true, requestId: "rid-1" } });
  expect(state.pendingText).toBe("hello"); // so a retry can send it again
});

test("a refusal, an interruption or a vanished conversation fail the turn with their own reason", () => {
  const api = new ApiError({ status: 422, code: "validation_error", message: "Bad.", retryable: false });
  for (const failure of [{ kind: "api", error: api }, { kind: "interrupted" }, { kind: "sessionGone" }] as const) {
    expect(run(emptyChat(), sent(), { type: "failed", failure }).turn).toEqual({ phase: "failed", failure });
  }
});

test("events that arrive when no turn is running are dropped", () => {
  const idle = emptyChat();
  expect(run(idle, delta("stray"))).toEqual(idle);
  const done = run(emptyChat(), sent(), ev({ type: "done" }));
  expect(run(done, delta("late"))).toEqual(done);
});

test("retrying drops what the failed attempt produced and keeps the user's message once", () => {
  const failed = run(
    emptyChat(),
    sent("question"),
    delta("part"),
    ev({ type: "tool_started", callId: "t1", toolId: "x", label: "X" }),
    ev({ type: "error", code: "harness_unavailable", retryable: true, requestId: null }),
  );
  const retried = run(failed, { type: "retryStarted" });
  expect(retried.items).toEqual([{ kind: "user", id: "u1", text: "question" }]);
  expect(retried.turn).toEqual({ phase: "streaming" });
  expect(retried.pendingText).toBe("question");
});

test("retrying leaves the earlier conversation untouched", () => {
  const history = emptyChat([
    { kind: "user", id: "h1", text: "old question" },
    { kind: "assistant", id: "h2", text: "old answer", complete: true },
  ]);
  const retried = run(history, sent("new"), delta("x"), { type: "failed", failure: { kind: "interrupted" } }, { type: "retryStarted" });
  expect(retried.items.map((i) => (i.kind === "tool" ? i.callId : i.id))).toEqual(["h1", "h2", "u1"]);
});

test("loading history replaces the timeline and resets the turn", () => {
  const items = [{ kind: "user", id: "h1", text: "hi" }] as const;
  const state = run(emptyChat(), sent(), { type: "historyLoaded", items: [...items] });
  expect(state).toEqual({ items, turn: { phase: "idle" }, pendingText: null });
});
