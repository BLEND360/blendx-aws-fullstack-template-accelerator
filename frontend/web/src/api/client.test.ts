import { ApiError, apiFetch } from "./client";
import { session } from "./session";

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

const fetchMock = vi.fn<typeof fetch>();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  session.onUnauthorized(null);
});

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  const error = await promise.then(
    () => undefined,
    (e: unknown) => e,
  );
  expect(error).toBeInstanceOf(ApiError);
  return error as ApiError;
}

test("sends the app token and returns the parsed body", async () => {
  session.setToken("tok");
  fetchMock.mockResolvedValue(json(200, { ok: true }));
  await expect(apiFetch("/api/v1/x")).resolves.toEqual({ ok: true });
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/v1/x");
  expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer tok");
});

test("sends no Authorization without a session, and JSON bodies with a content type", async () => {
  fetchMock.mockResolvedValue(json(201, {}));
  await apiFetch("/api/v1/x", { method: "POST", body: { a: 1 } });
  const init = fetchMock.mock.calls[0][1]!;
  expect(new Headers(init.headers).has("Authorization")).toBe(false);
  expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
  expect(init.body).toBe('{"a":1}');
});

test("204 resolves undefined", async () => {
  fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
  await expect(apiFetch("/api/v1/x")).resolves.toBeUndefined();
});

test("an error in the template's shape is exposed field by field", async () => {
  fetchMock.mockResolvedValue(
    json(422, {
      error: {
        code: "validation_error",
        message: "The request payload is not valid.",
        retryable: false,
        requestId: "rid-1",
        fields: [{ location: "body.name", message: "too short" }, { nonsense: true }],
      },
    }),
  );
  const error = await failure(apiFetch("/api/v1/x", { method: "POST", body: {} }));
  expect(error).toMatchObject({
    status: 422,
    code: "validation_error",
    message: "The request payload is not valid.",
    retryable: false,
    requestId: "rid-1",
    fields: [{ location: "body.name", message: "too short" }],
  });
});

test("a retryable error keeps its flag; the request id falls back to the header", async () => {
  fetchMock.mockResolvedValue(
    json(503, { error: { code: "data_throttled", message: "Busy.", retryable: true } }, { "X-Request-Id": "hdr-1" }),
  );
  expect(await failure(apiFetch("/api/v1/x"))).toMatchObject({ retryable: true, requestId: "hdr-1" });
});

test("a network failure is a generic retryable error", async () => {
  fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
  expect(await failure(apiFetch("/api/v1/x"))).toMatchObject({
    status: null,
    code: "network_error",
    retryable: true,
  });
});

test("an aborted request is rethrown as is", async () => {
  const controller = new AbortController();
  controller.abort();
  const abort = new DOMException("aborted", "AbortError");
  fetchMock.mockRejectedValue(abort);
  await expect(apiFetch("/api/v1/x", { signal: controller.signal })).rejects.toBe(abort);
});

test.each([502, 503, 504])("%i without the template's shape means the service is unavailable", async (status) => {
  fetchMock.mockResolvedValue(new Response("upstream says: secret-host:8000 refused", { status }));
  const error = await failure(apiFetch("/api/v1/x"));
  expect(error).toMatchObject({ code: "service_unavailable", retryable: true, status });
  expect(error.message).not.toMatch(/secret/);
});

test("an unrecognised error body is never exposed", async () => {
  fetchMock.mockResolvedValue(new Response("<html>Traceback: secret stack</html>", { status: 500 }));
  const error = await failure(apiFetch("/api/v1/x"));
  expect(error).toMatchObject({ code: "unexpected_response", retryable: false });
  expect(JSON.stringify(error)).not.toMatch(/secret/);
  expect(error.message).not.toMatch(/secret/);
});

test("a 2xx with a body that is not JSON is an unexpected response", async () => {
  fetchMock.mockResolvedValue(new Response("not json", { status: 200 }));
  expect(await failure(apiFetch("/api/v1/x"))).toMatchObject({ code: "unexpected_response" });
});

test("a 401 notifies the session and still throws", async () => {
  const handler = vi.fn();
  session.onUnauthorized(handler);
  fetchMock.mockResolvedValue(json(401, { error: { code: "auth_invalid_token", message: "Sign in again." } }));
  expect(await failure(apiFetch("/auth/me"))).toMatchObject({ status: 401 });
  expect(handler).toHaveBeenCalledOnce();
});

test("paths outside /api and /auth do not compile", () => {
  // @ts-expect-error absolute URLs are not API paths
  void (() => apiFetch("https://elsewhere.test/x"));
  // @ts-expect-error neither are unprefixed paths
  void (() => apiFetch("/other/x"));
});
