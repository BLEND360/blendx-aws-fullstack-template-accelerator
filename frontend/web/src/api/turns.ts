import { apiOpenStream } from "./client";
import { createSseParser } from "./events";
import type { TurnEvent } from "./events";

/** How a turn ended: its final event was `done`, its final event was `error`, or the body closed with neither. */
export type TurnEnd = "done" | "error" | "interrupted";

/**
 * Sends a message and delivers the turn's events as they arrive.
 * Throws ApiError when the API refuses the message before any stream starts (unknown session,
 * empty message, no assistant configured, session expired). An aborted `signal` rejects with AbortError.
 */
export async function streamTurn(
  sessionId: string,
  text: string,
  signal: AbortSignal,
  onEvent: (event: TurnEvent) => void,
): Promise<TurnEnd> {
  const response = await apiOpenStream(`/api/v1/sessions/${encodeURIComponent(sessionId)}/messages`, {
    method: "POST",
    body: { text },
    signal,
  });
  if (!response.body) return "interrupted";

  let end: TurnEnd | null = null;
  const parser = createSseParser((event) => {
    if (end) return; // nothing follows a terminal event
    onEvent(event);
    if (event.type === "done") end = "done";
    else if (event.type === "error") end = "error";
  });

  const reader = response.body.getReader();
  // `stream: true` keeps a character that was split across two chunks until the rest arrives.
  const decoder = new TextDecoder();
  try {
    while (!end) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.push(decoder.decode(value, { stream: true }));
    }
    if (!end) parser.push(decoder.decode());
  } finally {
    parser.end();
    reader.cancel().catch(() => {}); // release the connection once the turn is over
  }
  return end ?? "interrupted";
}
