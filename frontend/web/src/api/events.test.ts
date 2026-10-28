import { createSseParser } from "./events";
import type { TurnEvent } from "./events";

const block = (name: string, data: unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
const PING = ": ping\n\n";

const TEXT_TURN = block("delta", { text: "Hel" }) + PING + block("delta", { text: "lo ✓ wörld" }) + block("done", {});
const TOOL_TURN =
  block("delta", { text: "Let me check. " }) +
  block("tool_started", { callId: "t1", toolId: "current_time", label: "Checking the time" }) +
  PING +
  block("tool_input", { callId: "t1", input: { format: "iso" } }) +
  block("tool_finished", { callId: "t1", status: "success", result: { time: "2026-10-09T16:00:00+00:00" } }) +
  block("delta", { text: "It is late." }) +
  block("done", {});
const FAILED_TURN =
  block("delta", { text: "Working" }) + block("error", { code: "harness_unavailable", retryable: true, requestId: "rid-1" });

function parse(chunks: string[]): TurnEvent[] {
  const events: TurnEvent[] = [];
  const parser = createSseParser((e) => events.push(e));
  chunks.forEach((c) => parser.push(c));
  parser.end();
  return events;
}

const WHOLE = (s: string) => parse([s]);

test("a text turn is its deltas then done", () => {
  expect(WHOLE(TEXT_TURN)).toEqual([
    { type: "delta", text: "Hel" },
    { type: "delta", text: "lo ✓ wörld" },
    { type: "done" },
  ]);
});

test("a tool turn keeps every field of every tool event", () => {
  expect(WHOLE(TOOL_TURN)).toEqual([
    { type: "delta", text: "Let me check. " },
    { type: "tool_started", callId: "t1", toolId: "current_time", label: "Checking the time" },
    { type: "tool_input", callId: "t1", input: { format: "iso" } },
    { type: "tool_finished", callId: "t1", status: "success", result: { time: "2026-10-09T16:00:00+00:00" } },
    { type: "delta", text: "It is late." },
    { type: "done" },
  ]);
});

test("an error event carries its code, whether to retry and the request id", () => {
  expect(WHOLE(FAILED_TURN).at(-1)).toEqual({ type: "error", code: "harness_unavailable", retryable: true, requestId: "rid-1" });
});

describe.each([
  ["text", TEXT_TURN],
  ["tool", TOOL_TURN],
  ["failed", FAILED_TURN],
])("the %s stream however the network splits it", (_name, stream) => {
  const reference = WHOLE(stream);

  test("split in two at every possible position", () => {
    for (let i = 0; i <= stream.length; i++) {
      expect(parse([stream.slice(0, i), stream.slice(i)])).toEqual(reference);
    }
  });

  test("one character at a time", () => {
    expect(parse([...stream])).toEqual(reference);
  });

  test("in pieces of every size from 2 to 11", () => {
    for (let size = 2; size <= 11; size++) {
      const pieces = stream.match(new RegExp(`[\\s\\S]{1,${size}}`, "g")) ?? [];
      expect(parse(pieces)).toEqual(reference);
    }
  });

  test("with Windows line endings, split anywhere", () => {
    const crlf = stream.replace(/\n/g, "\r\n");
    expect(parse([crlf])).toEqual(reference);
    for (let i = 0; i <= crlf.length; i++) {
      expect(parse([crlf.slice(0, i), crlf.slice(i)])).toEqual(reference);
    }
  });
});

test("an event is delivered as soon as it is complete, not at the end", () => {
  const seen: TurnEvent[] = [];
  const parser = createSseParser((e) => seen.push(e));
  parser.push('event: delta\ndata: {"text": "He');
  expect(seen).toEqual([]);
  parser.push('llo"}\n');
  expect(seen).toEqual([]); // still no blank line
  parser.push("\n");
  expect(seen).toEqual([{ type: "delta", text: "Hello" }]);
});

test("keepalive comments alone produce nothing", () => {
  expect(parse([PING, PING, ": still here\n\n"])).toEqual([]);
});

test("a comment inside an event does not disturb it", () => {
  expect(WHOLE('event: delta\n: ping\ndata: {"text": "x"}\n\n')).toEqual([{ type: "delta", text: "x" }]);
});

test("unknown event names, data that is not JSON and events missing fields are ignored", () => {
  const noise =
    block("something_new", { a: 1 }) +
    "event: delta\ndata: not json\n\n" +
    block("delta", { nope: true }) +
    block("tool_started", { callId: "t1" }) +
    block("tool_finished", { callId: "t1", status: "weird", result: {} }) +
    block("error", { code: "x" }) + // no retryable
    "data: orphan\n\n" + // no event name
    block("delta", { text: "kept" });
  expect(WHOLE(noise)).toEqual([{ type: "delta", text: "kept" }]);
});

test("a missing request id on an error is null", () => {
  expect(WHOLE(block("error", { code: "internal_error", retryable: false }))).toEqual([
    { type: "error", code: "internal_error", retryable: false, requestId: null },
  ]);
});

test("an event that never finished is dropped when the input ends", () => {
  expect(parse(['event: delta\ndata: {"text": "cut off"}'])).toEqual([]);
});

test("a data field split over several data lines is joined before it is read", () => {
  expect(WHOLE('event: delta\ndata: {"text":\ndata: "two lines"}\n\n')).toEqual([{ type: "delta", text: "two lines" }]);
});
