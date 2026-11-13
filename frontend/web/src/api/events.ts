/** The events of one conversation turn, as the API streams them (server-sent events).
 * The vocabulary is closed and owned by the API; this file only reads it. */

export type TurnEvent =
  | { type: "delta"; text: string }
  | { type: "tool_started"; callId: string; toolId: string; label: string }
  | { type: "tool_input"; callId: string; input: unknown }
  | { type: "tool_finished"; callId: string; status: "success" | "error"; result: unknown }
  | { type: "done" }
  | { type: "error"; code: string; retryable: boolean; requestId: string | null };

export interface SseParser {
  /** Feed decoded text in any pieces; each complete event is delivered as soon as it is complete. */
  push(chunk: string): void;
  /** End of input: an event that never finished is dropped. */
  end(): void;
}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null;
const isString = (value: unknown): value is string => typeof value === "string";

/** A known event with the fields it must have, or null: anything else is ignored, not an error. */
function toTurnEvent(name: string, data: unknown): TurnEvent | null {
  const d = isRecord(data) ? data : {};
  switch (name) {
    case "delta":
      return isString(d.text) ? { type: "delta", text: d.text } : null;
    case "tool_started":
      return isString(d.callId) && isString(d.toolId) && isString(d.label)
        ? { type: "tool_started", callId: d.callId, toolId: d.toolId, label: d.label }
        : null;
    case "tool_input":
      return isString(d.callId) ? { type: "tool_input", callId: d.callId, input: d.input } : null;
    case "tool_finished":
      return isString(d.callId) && (d.status === "success" || d.status === "error")
        ? { type: "tool_finished", callId: d.callId, status: d.status, result: d.result }
        : null;
    case "done":
      return { type: "done" };
    case "error":
      return isString(d.code) && typeof d.retryable === "boolean"
        ? { type: "error", code: d.code, retryable: d.retryable, requestId: isString(d.requestId) ? d.requestId : null }
        : null;
    default:
      return null;
  }
}

function parseBlock(block: string): TurnEvent | null {
  let name: string | null = null;
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith(":")) continue; // a comment: the server's keepalive
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") name = value;
    else if (field === "data") data.push(value);
  }
  if (name === null) return null;
  try {
    return toTurnEvent(name, data.length ? JSON.parse(data.join("\n")) : {});
  } catch {
    return null; // data that is not JSON
  }
}

export function createSseParser(onEvent: (event: TurnEvent) => void): SseParser {
  let buffer = "";
  return {
    push(chunk) {
      buffer += chunk;
      // An event ends at a blank line. The separator can arrive in pieces ("\r\n\r" then "\n"),
      // so it is searched for in the whole buffer every time.
      for (;;) {
        const separator = /\r?\n\r?\n/.exec(buffer);
        if (!separator) return;
        const block = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator[0].length);
        const event = parseBlock(block);
        if (event) onEvent(event);
      }
    },
    end() {
      buffer = "";
    },
  };
}
