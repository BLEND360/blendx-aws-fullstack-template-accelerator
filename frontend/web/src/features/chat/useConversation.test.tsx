import { act, renderHook, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import type { ReactNode } from "react";
import { useConversation } from "./useConversation";

const fetchMock = vi.fn<typeof fetch>();
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const notFound = () => json(404, { error: { code: "not_found", message: "Session not found.", retryable: false, requestId: "r" } });
const calls = () => fetchMock.mock.calls.map(([url, init]) => `${init?.method ?? "GET"} ${String(url)}`);

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

test("with nothing remembered it creates a conversation, remembers it and starts empty", async () => {
  fetchMock.mockResolvedValue(json(201, { id: "new1" }));
  const { result } = renderHook(() => useConversation());
  expect(result.current.state.status).toBe("loading");
  await waitFor(() => expect(result.current.state.status).toBe("ready"));
  expect(result.current.state).toEqual({ status: "ready", sessionId: "new1", history: [] });
  expect(localStorage.getItem("chat.sessionId")).toBe("new1");
  expect(calls()).toEqual(["POST /api/v1/sessions"]);
});

test("with one remembered it loads its history in order, as user and assistant items", async () => {
  localStorage.setItem("chat.sessionId", "old1");
  fetchMock.mockResolvedValue(
    json(200, {
      messages: [
        { role: "user", text: "hi", createdAt: "t1" },
        { role: "assistant", text: "hello", createdAt: "t2" },
      ],
    }),
  );
  const { result } = renderHook(() => useConversation());
  await waitFor(() => expect(result.current.state.status).toBe("ready"));
  expect(result.current.state).toMatchObject({
    sessionId: "old1",
    history: [
      { kind: "user", text: "hi" },
      { kind: "assistant", text: "hello", complete: true },
    ],
  });
  expect(calls()).toEqual(["GET /api/v1/sessions/old1/messages"]); // nothing was created
});

test("a remembered conversation that no longer exists is forgotten and replaced, without an error", async () => {
  localStorage.setItem("chat.sessionId", "gone");
  fetchMock.mockResolvedValueOnce(notFound()).mockResolvedValueOnce(json(201, { id: "fresh" }));
  const { result } = renderHook(() => useConversation());
  await waitFor(() => expect(result.current.state.status).toBe("ready"));
  expect(result.current.state).toEqual({ status: "ready", sessionId: "fresh", history: [] });
  expect(localStorage.getItem("chat.sessionId")).toBe("fresh");
  expect(calls()).toEqual(["GET /api/v1/sessions/gone/messages", "POST /api/v1/sessions"]);
});

test("a failure to create is an error with its request id, and reload tries again", async () => {
  fetchMock
    .mockResolvedValueOnce(json(503, { error: { code: "data_unavailable", message: "Down.", retryable: true, requestId: "rid-503" } }))
    .mockResolvedValueOnce(json(201, { id: "ok" }));
  const { result } = renderHook(() => useConversation());
  await waitFor(() => expect(result.current.state.status).toBe("error"));
  expect(result.current.state).toMatchObject({ error: { message: "Down.", requestId: "rid-503", retryable: true } });
  expect(localStorage.getItem("chat.sessionId")).toBeNull();

  act(() => result.current.reload());
  await waitFor(() => expect(result.current.state.status).toBe("ready"));
  expect(result.current.state).toMatchObject({ sessionId: "ok" });
});

test("a failure to load history keeps the remembered conversation for the retry", async () => {
  localStorage.setItem("chat.sessionId", "keep");
  fetchMock.mockResolvedValueOnce(new Response("", { status: 503 })).mockResolvedValueOnce(json(200, { messages: [] }));
  const { result } = renderHook(() => useConversation());
  await waitFor(() => expect(result.current.state.status).toBe("error"));
  expect(localStorage.getItem("chat.sessionId")).toBe("keep");
  act(() => result.current.reload());
  await waitFor(() => expect(result.current.state.status).toBe("ready"));
  expect(result.current.state).toMatchObject({ sessionId: "keep" });
});

test("starting a new conversation replaces the remembered one", async () => {
  localStorage.setItem("chat.sessionId", "first");
  fetchMock.mockResolvedValueOnce(json(200, { messages: [] })).mockResolvedValueOnce(json(201, { id: "second" }));
  const { result } = renderHook(() => useConversation());
  await waitFor(() => expect(result.current.state.status).toBe("ready"));

  act(() => result.current.startNew());
  await waitFor(() => expect(result.current.state).toMatchObject({ status: "ready", sessionId: "second" }));
  expect(localStorage.getItem("chat.sessionId")).toBe("second");
});

test("reloading the page keeps the same conversation", async () => {
  fetchMock.mockResolvedValueOnce(json(201, { id: "stay" }));
  const first = renderHook(() => useConversation());
  await waitFor(() => expect(first.result.current.state.status).toBe("ready"));
  first.unmount();

  fetchMock.mockResolvedValueOnce(json(200, { messages: [{ role: "user", text: "before reload", createdAt: "t" }] }));
  const second = renderHook(() => useConversation());
  await waitFor(() => expect(second.result.current.state.status).toBe("ready"));
  expect(second.result.current.state).toMatchObject({ sessionId: "stay", history: [{ text: "before reload" }] });
});

test("forgetting drops the remembered id without opening another", async () => {
  fetchMock.mockResolvedValueOnce(json(201, { id: "x" }));
  const { result } = renderHook(() => useConversation());
  await waitFor(() => expect(result.current.state.status).toBe("ready"));
  act(() => result.current.forget());
  expect(localStorage.getItem("chat.sessionId")).toBeNull();
  expect(fetchMock).toHaveBeenCalledOnce();
});

test("StrictMode's double effect does not create two conversations", async () => {
  fetchMock.mockResolvedValue(json(201, { id: "only" }));
  const wrapper = ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>;
  const { result } = renderHook(() => useConversation(), { wrapper });
  await waitFor(() => expect(result.current.state.status).toBe("ready"));
  expect(calls()).toEqual(["POST /api/v1/sessions"]);
});
