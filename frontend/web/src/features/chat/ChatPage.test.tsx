import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeModeProvider } from "../../theme/ThemeModeProvider";
import { controlledResponse, SSE_PING, sseBlock, streamResponse } from "../../test/sse";
import { ChatPage } from "./ChatPage";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const apiError = (status: number, code: string, message: string, retryable = false, requestId = "rid-1") =>
  json(status, { error: { code, message, retryable, requestId } });

type Route = () => Response | Promise<Response>;
const fetchMock = vi.fn<typeof fetch>();

/** Routes by "METHOD path"; anything else is a 404 so a stray call is noticed. */
function api(routes: Record<string, Route>) {
  fetchMock.mockImplementation((url, init) => {
    const route = routes[`${init?.method ?? "GET"} ${String(url)}`];
    return Promise.resolve(route ? route() : apiError(404, "not_found", "Not found."));
  });
}
const posts = () => fetchMock.mock.calls.filter(([url, init]) => init?.method === "POST" && String(url).endsWith("/messages"));

const CREATE = { "POST /api/v1/sessions": () => json(201, { id: "s1" }), "GET /api/v1/sessions/s1/messages": () => json(200, { messages: [] }) };
const TURN = "POST /api/v1/sessions/s1/messages";

function show(replayMode = false) {
  return render(
    <ThemeModeProvider>
      <ChatPage replayMode={replayMode} />
    </ThemeModeProvider>,
  );
}
const field = () => screen.getByRole("textbox", { name: "Message" });
const send = async (text: string) => {
  await userEvent.type(field(), text);
  await userEvent.click(screen.getByRole("button", { name: "Send" }));
};
const log = () => screen.getByRole("log");

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  Element.prototype.scrollIntoView = vi.fn();
});

// ============================ opening the conversation ============================
describe("opening the conversation", () => {
  test("shows a loading indicator and refuses to send while the conversation is created", async () => {
    let release: (r: Response) => void = () => {};
    api({ ...CREATE, "POST /api/v1/sessions": () => new Promise<Response>((resolve) => (release = resolve)) });
    show();
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await userEvent.type(field(), "typing is fine");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    release(json(201, { id: "s1" }));
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    expect(screen.queryByRole("status", { name: "Loading" })).not.toBeInTheDocument();
  });

  test("a new conversation is empty and invites the first message", async () => {
    api(CREATE);
    show();
    expect(await screen.findByText("Ask about projects, items, insights or workspace information.")).toBeInTheDocument();
    expect(localStorage.getItem("chat.sessionId")).toBe("s1");
  });

  test("a remembered conversation shows its history in order, user and assistant told apart", async () => {
    localStorage.setItem("chat.sessionId", "s1");
    api({
      "GET /api/v1/sessions/s1/messages": () =>
        json(200, {
          messages: [
            { role: "user", text: "What is 2+2?", createdAt: "t1" },
            { role: "assistant", text: "Four.", createdAt: "t2" },
            { role: "user", text: "Thanks", createdAt: "t3" },
          ],
        }),
    });
    show();
    await screen.findByText("Four.");
    const text = log().textContent ?? "";
    expect(text.indexOf("What is 2+2?")).toBeLessThan(text.indexOf("Four."));
    expect(text.indexOf("Four.")).toBeLessThan(text.indexOf("Thanks"));
    expect(within(log()).getAllByText("You")).toHaveLength(2);
    expect(within(log()).getAllByText("Assistant")).toHaveLength(1);
    expect(screen.queryByText("Ask about projects, items, insights or workspace information.")).not.toBeInTheDocument();
  });

  test("a remembered conversation that no longer exists is replaced quietly", async () => {
    localStorage.setItem("chat.sessionId", "stale");
    api({ "GET /api/v1/sessions/stale/messages": () => apiError(404, "not_found", "Session not found."), ...CREATE });
    show();
    expect(await screen.findByText("Ask about projects, items, insights or workspace information.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(localStorage.getItem("chat.sessionId")).toBe("s1");
  });

  test("a failure to open shows the error with its request id and retry works", async () => {
    let calls = 0;
    api({ ...CREATE, "POST /api/v1/sessions": () => (++calls === 1 ? apiError(503, "data_unavailable", "The data store is down.", true, "rid-open") : json(201, { id: "s1" })) });
    show();
    expect(await screen.findByText("The data store is down.")).toBeInTheDocument();
    expect(screen.getByText("Request ID: rid-open")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Ask about projects, items, insights or workspace information.")).toBeInTheDocument();
  });

  test("new conversation leaves the old one behind and remembers the new", async () => {
    localStorage.setItem("chat.sessionId", "s1");
    let created = 0;
    api({
      "GET /api/v1/sessions/s1/messages": () => json(200, { messages: [{ role: "user", text: "old talk", createdAt: "t" }] }),
      "POST /api/v1/sessions": () => json(201, { id: `n${++created}` }),
      "GET /api/v1/sessions/n1/messages": () => json(200, { messages: [] }),
    });
    show();
    await screen.findByText("old talk");
    await userEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(await screen.findByText("Ask about projects, items, insights or workspace information.")).toBeInTheDocument();
    expect(screen.queryByText("old talk")).not.toBeInTheDocument();
    expect(localStorage.getItem("chat.sessionId")).toBe("n1");
  });

  test("the demo notice shows only when the API is answering with recordings", async () => {
    api(CREATE);
    const first = show(true);
    expect(screen.getByText("Demo mode: these responses are recorded, not live.")).toBeInTheDocument();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    first.unmount();
    show(false);
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    expect(screen.queryByText(/Demo mode/)).not.toBeInTheDocument();
  });
});

// ================================ a turn ================================
describe("a turn", () => {
  test("the message shows at once, the field empties, and sending is blocked until the answer ends", async () => {
    const live = controlledResponse();
    api({ ...CREATE, [TURN]: () => live.response });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    await send("hello agent");

    expect(within(log()).getByText("hello agent")).toBeInTheDocument(); // before any event arrived
    expect(field()).toHaveValue("");
    expect(screen.getByText("Thinking…")).toBeInTheDocument();
    expect(log()).toHaveAttribute("aria-busy", "true");
    await userEvent.type(field(), "another{Enter}");
    expect(posts()).toHaveLength(1); // the second message was not sent

    live.push(sseBlock("delta", { text: "ok" }) + sseBlock("done", {}));
    live.close();
    await waitFor(() => expect(log()).toHaveAttribute("aria-busy", "false"));
    expect(field()).toHaveFocus(); // the cursor is back
  });

  test("the answer grows as pieces arrive, however they are cut", async () => {
    const live = controlledResponse();
    api({ ...CREATE, [TURN]: () => live.response });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    await send("hi");

    live.push(sseBlock("delta", { text: "Hel" }));
    expect(await within(log()).findByText("Hel")).toBeInTheDocument();
    live.push('event: delta\ndata: {"text": "lo, wör'); // an event cut in half
    live.push(`ld"}\n\n${SSE_PING}`);
    expect(await within(log()).findByText("Hello, wörld")).toBeInTheDocument();
    live.push(sseBlock("done", {}));
    live.close();
    await waitFor(() => expect(log()).toHaveAttribute("aria-busy", "false"));
    expect(screen.queryByText(/ping/)).not.toBeInTheDocument(); // keepalive is invisible
  });

  test("a tool appears between two stretches of text and goes from running to done", async () => {
    const live = controlledResponse();
    api({ ...CREATE, [TURN]: () => live.response });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    await send("what time is it");

    live.push(sseBlock("delta", { text: "Let me check. " }));
    live.push(sseBlock("tool_started", { callId: "t1", toolId: "current_time", label: "Checking the time" }));
    const card = await screen.findByRole("group", { name: "Checking the time: Running" });
    live.push(sseBlock("tool_input", { callId: "t1", input: { format: "iso" } }));
    await waitFor(() => expect(card).toHaveTextContent('"format": "iso"'));
    live.push(sseBlock("tool_finished", { callId: "t1", status: "success", result: { time: "now" } }));
    await screen.findByRole("group", { name: "Checking the time: Done" });
    live.push(sseBlock("delta", { text: "It is late." }) + sseBlock("done", {}));
    live.close();
    await within(log()).findByText("It is late.");

    const order = [...log().querySelectorAll("div, section")].map((n) => n.textContent ?? "");
    const full = log().textContent ?? "";
    expect(full.indexOf("Let me check.")).toBeLessThan(full.indexOf("Checking the time"));
    expect(full.indexOf("Checking the time")).toBeLessThan(full.indexOf("It is late."));
    expect(order.length).toBeGreaterThan(0);
  });

  test("two tools in one turn are two cards, each with its own data", async () => {
    api({
      ...CREATE,
      [TURN]: () =>
        streamResponse([
          sseBlock("tool_started", { callId: "a", toolId: "x", label: "First tool" }),
          sseBlock("tool_started", { callId: "b", toolId: "y", label: "Second tool" }),
          sseBlock("tool_input", { callId: "b", input: { n: 2 } }),
          sseBlock("tool_finished", { callId: "a", status: "success", result: { r: 1 } }),
          sseBlock("tool_finished", { callId: "b", status: "error", result: { code: "tool_failed" } }),
          sseBlock("done", {}),
        ]),
    });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    await send("go");
    const first = await screen.findByRole("group", { name: "First tool: Done" });
    const second = await screen.findByRole("group", { name: "Second tool: Failed" });
    expect(first).toHaveTextContent('"r": 1');
    expect(second).toHaveTextContent('"n": 2');
    expect(second).toHaveTextContent("tool_failed");
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test("the newest text is kept in view while it arrives", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    api({ ...CREATE, [TURN]: () => streamResponse([sseBlock("delta", { text: "a" }), sseBlock("done", {})]) });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    const before = scroll.mock.calls.length;
    await send("hi");
    await within(log()).findByText("a");
    expect(scroll.mock.calls.length).toBeGreaterThan(before);
  });

  test("announces that the assistant is responding and when the response is complete", async () => {
    const live = controlledResponse();
    api({ ...CREATE, [TURN]: () => live.response });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    const status = () => screen.getAllByRole("status").find((n) => n.getAttribute("aria-live") === "polite")!;
    expect(status()).toHaveTextContent("");
    await send("hi");
    await waitFor(() => expect(status()).toHaveTextContent("The assistant is responding"));
    live.push(sseBlock("delta", { text: "x" }) + sseBlock("done", {}));
    live.close();
    await waitFor(() => expect(status()).toHaveTextContent("Response complete"));
  });

  test("everything can be done with the keyboard alone", async () => {
    api({ ...CREATE, [TURN]: () => streamResponse([sseBlock("delta", { text: "hi back" }), sseBlock("done", {})]) });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    expect(field()).toHaveFocus();
    await userEvent.keyboard("hello{Enter}");
    expect(await within(log()).findByText("hi back")).toBeInTheDocument();
    await userEvent.tab(); // Send
    await userEvent.tab(); // New conversation, reached after the field and the action
    expect(document.activeElement).not.toBe(document.body);
  });
});

// ================================ failures ================================
describe("when a turn fails", () => {
  test("a refusal before the answer shows the API's message and request id, with no retry when it would not help", async () => {
    api({ ...CREATE, [TURN]: () => apiError(422, "validation_error", "The request is not valid.", false, "rid-422") });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    await send("hi");
    expect(await screen.findByText("The request is not valid.")).toBeInTheDocument();
    expect(screen.getByText("Request ID: rid-422")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(field()).toHaveFocus();
  });

  test("a retryable refusal offers retry, and retry sends the same message without showing it twice", async () => {
    let calls = 0;
    api({
      ...CREATE,
      [TURN]: () => (++calls === 1 ? apiError(503, "harness_unavailable", "The assistant is down.", true) : streamResponse([sseBlock("delta", { text: "back" }), sseBlock("done", {})])),
    });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    await send("same question");
    await screen.findByText("The assistant is down.");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await within(log()).findByText("back")).toBeInTheDocument();
    expect(within(log()).getAllByText("same question")).toHaveLength(1);
    expect(posts().map(([, init]) => JSON.parse(String(init?.body)))).toEqual([{ text: "same question" }, { text: "same question" }]);
    expect(screen.queryByText("The assistant is down.")).not.toBeInTheDocument();
  });

  test("a conversation that no longer exists is forgotten and a new one is offered", async () => {
    api({ ...CREATE, [TURN]: () => apiError(404, "not_found", "Session not found.") });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    await send("hi");
    expect(await screen.findByText("This conversation no longer exists.")).toBeInTheDocument();
    expect(localStorage.getItem("chat.sessionId")).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();

    api({ "POST /api/v1/sessions": () => json(201, { id: "s2" }), "GET /api/v1/sessions/s2/messages": () => json(200, { messages: [] }) });
    await userEvent.click(screen.getByRole("button", { name: "Start a new conversation" }));
    expect(await screen.findByText("Ask about projects, items, insights or workspace information.")).toBeInTheDocument();
    expect(localStorage.getItem("chat.sessionId")).toBe("s2");
  });

  test("an error event keeps the text, shows our own sentence with the request id, and retries the turn", async () => {
    let calls = 0;
    api({
      ...CREATE,
      [TURN]: () =>
        ++calls === 1
          ? streamResponse([
              sseBlock("delta", { text: "Working on it" }),
              sseBlock("tool_started", { callId: "t1", toolId: "x", label: "A tool" }),
              sseBlock("error", { code: "harness_unavailable", retryable: true, requestId: "rid-evt" }),
            ])
          : streamResponse([sseBlock("delta", { text: "Done properly" }), sseBlock("done", {})]),
    });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    await send("do it");
    expect(await screen.findByText("The assistant is temporarily unavailable.")).toBeInTheDocument();
    expect(screen.getByText("Request ID: rid-evt")).toBeInTheDocument();
    expect(within(log()).getByText("Working on it")).toBeInTheDocument(); // kept
    expect(screen.getByRole("group", { name: "A tool: Running" })).toBeInTheDocument(); // kept

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await within(log()).findByText("Done properly")).toBeInTheDocument();
    expect(within(log()).queryByText("Working on it")).not.toBeInTheDocument(); // the failed attempt was replaced
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(within(log()).getAllByText("do it")).toHaveLength(1);
  });

  test("an error that is not retryable offers no retry", async () => {
    api({ ...CREATE, [TURN]: () => streamResponse([sseBlock("error", { code: "harness_misconfigured", retryable: false, requestId: "r" })]) });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    await send("hi");
    expect(await screen.findByText("No assistant is configured for this deployment.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  test("a code the page does not know gets the default sentence and never shows the code", async () => {
    api({ ...CREATE, [TURN]: () => streamResponse([sseBlock("error", { code: "arn:aws:iam::123456789012:role/secret", retryable: false, requestId: null })]) });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    await send("hi");
    expect(await screen.findByText("The response could not be completed.")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("arn:aws");
    expect(document.body).not.toHaveTextContent("Request ID"); // there was none
  });

  test("a response that stops without an end says it was interrupted, keeps the text and can be retried", async () => {
    api({ ...CREATE, [TURN]: () => streamResponse([sseBlock("delta", { text: "half an ans" })]) });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    await send("hi");
    expect(await screen.findByText("The response was interrupted.")).toBeInTheDocument();
    expect(within(log()).getByText("half an ans")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  test("the page can be left with the keyboard from a failure: retry and new conversation are real buttons", async () => {
    api({ ...CREATE, [TURN]: () => apiError(503, "harness_unavailable", "Down.", true) });
    show();
    await screen.findByText("Ask about projects, items, insights or workspace information.");
    await send("hi");
    await screen.findByText("Down.");
    const retry = screen.getByRole("button", { name: "Retry" });
    retry.focus();
    expect(retry).toHaveFocus();
    expect(screen.getByRole("button", { name: "New conversation" })).toBeEnabled();
  });
});
