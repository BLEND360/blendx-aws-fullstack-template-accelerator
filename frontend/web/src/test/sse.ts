/** Helpers to build server-sent-event responses for tests, with the body split however a test wants. */

const encoder = new TextEncoder();

/** One event as the API writes it. */
export function sseBlock(name: string, data: unknown): string {
  return `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
}

export const SSE_PING = ": ping\n\n";

/** A 200 text/event-stream response whose body arrives as the given chunks (strings or raw bytes). */
export function streamResponse(chunks: (string | Uint8Array)[], init: ResponseInit = {}): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" }, ...init });
}

/** Cut text into pieces of `size` characters: the simplest "the network split it" case. */
export function pieces(text: string, size: number): string[] {
  return text.match(new RegExp(`[\\s\\S]{1,${size}}`, "g")) ?? [];
}

/** A stream that delivers `first`, then stays open until the request's signal aborts, like a real fetch body. */
export function hangingResponse(first: string, signal: AbortSignal | null | undefined): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(first));
      signal?.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

/** A response whose body the test feeds by hand, so it can look at the screen between two pieces. */
export function controlledResponse() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    push: (text: string) => controller.enqueue(encoder.encode(text)),
    close: () => controller.close(),
  };
}
