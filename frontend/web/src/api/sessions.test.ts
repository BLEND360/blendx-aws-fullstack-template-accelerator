import { ApiError } from "./client";
import { createSession, fetchHistory } from "./sessions";

const fetchMock = vi.fn<typeof fetch>();
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

test("creating posts an empty body and returns only the id", async () => {
  fetchMock.mockResolvedValue(json(201, { id: "abc", createdAt: "x", config: { modelId: "m" } }));
  await expect(createSession()).resolves.toEqual({ id: "abc" });
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/v1/sessions");
  expect(init?.method).toBe("POST");
  expect(init?.body).toBe("{}"); // the client chooses nothing: no model, no tools
});

test("history is read from the session's messages route and returned as a list", async () => {
  const messages = [{ role: "user", text: "hi", createdAt: "2026-10-09T10:00:00+00:00" }];
  fetchMock.mockResolvedValue(json(200, { messages }));
  await expect(fetchHistory("abc")).resolves.toEqual(messages);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/sessions/abc/messages");
});

test("a session id is encoded into the path, never trusted as part of it", async () => {
  fetchMock.mockResolvedValue(json(200, { messages: [] }));
  await fetchHistory("a/b?c");
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/sessions/a%2Fb%3Fc/messages");
});

test("an unknown session is a classified 404", async () => {
  fetchMock.mockResolvedValue(json(404, { error: { code: "not_found", message: "Session not found.", retryable: false } }));
  const error = await fetchHistory("gone").catch((e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ status: 404, code: "not_found" });
});
