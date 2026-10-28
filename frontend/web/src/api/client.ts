import { messages } from "../messages";
import { isRecord } from "./guards";
import { session } from "./session";

/** Only origin-relative API paths compile: no base URL exists to configure. */
export type ApiPath = `/api/${string}` | `/auth/${string}`;

export interface ApiFieldError {
  readonly location: string;
  readonly message: string;
}

export interface ApiErrorInit {
  status: number | null;
  code: string;
  message: string;
  retryable: boolean;
  requestId?: string | null;
  fields?: readonly ApiFieldError[];
}

/** Everything the UI may know about a failed call. The response body is never kept. */
export class ApiError extends Error {
  readonly status: number | null;
  readonly code: string;
  readonly retryable: boolean;
  readonly requestId: string | null;
  readonly fields: readonly ApiFieldError[];

  constructor(init: ApiErrorInit) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.retryable = init.retryable;
    this.requestId = init.requestId ?? null;
    this.fields = init.fields ?? [];
  }
}

export interface ApiRequest {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

const REQUEST_ID_HEADER = "X-Request-Id";

export function unexpectedError(status: number | null = null): ApiError {
  return new ApiError({ status, code: "unexpected_response", message: messages.unexpected, retryable: false });
}

/** Anything thrown that is not already an ApiError, as one. */
export function asApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : unexpectedError();
}

function parseFields(value: unknown): ApiFieldError[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) =>
    isRecord(item) && typeof item.location === "string" && typeof item.message === "string"
      ? [{ location: item.location, message: item.message }]
      : [],
  );
}

async function toApiError(response: Response): Promise<ApiError> {
  const headerId = response.headers.get(REQUEST_ID_HEADER);
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = undefined;
  }
  const error = isRecord(body) ? body.error : undefined;
  if (isRecord(error) && typeof error.code === "string" && typeof error.message === "string") {
    return new ApiError({
      status: response.status,
      code: error.code,
      message: error.message,
      retryable: error.retryable === true,
      requestId: typeof error.requestId === "string" ? error.requestId : headerId,
      fields: parseFields(error.fields),
    });
  }
  // Not the template's shape: say something fixed, never what came back.
  if ([502, 503, 504].includes(response.status)) {
    return new ApiError({
      status: response.status,
      code: "service_unavailable",
      message: messages.serviceUnavailable,
      retryable: true,
      requestId: headerId,
    });
  }
  return new ApiError({ ...unexpectedError(response.status), requestId: headerId });
}

/** The one place a request leaves the app: authentication, error classification and the 401 signal.
 * Returns the response only when it is 2xx; anything else is an ApiError. */
async function send(path: ApiPath, request: ApiRequest, accept: string): Promise<Response> {
  const headers = new Headers({ Accept: accept });
  if (request.body !== undefined) headers.set("Content-Type", "application/json");
  const token = session.getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(path, {
      method: request.method ?? "GET",
      headers,
      body: request.body === undefined ? undefined : JSON.stringify(request.body),
      signal: request.signal,
    });
  } catch (error) {
    if (request.signal?.aborted) throw error; // a cancellation, not a failure
    throw new ApiError({ status: null, code: "network_error", message: messages.networkError, retryable: true });
  }

  if (!response.ok) {
    if (response.status === 401) session.notifyUnauthorized();
    throw await toApiError(response);
  }
  return response;
}

// The body is trusted to match T: the API contract is the guarantee.
export async function apiFetch<T>(path: ApiPath, request: ApiRequest = {}): Promise<T> {
  const response = await send(path, request, "application/json");
  if (response.status === 204) return undefined as T;
  try {
    return (await response.json()) as T;
  } catch {
    throw unexpectedError(response.status);
  }
}

/** Opens a streamed response (server-sent events). The caller reads `response.body`; everything
 * that can go wrong before the stream starts has already been turned into an ApiError. */
export function apiOpenStream(path: ApiPath, request: ApiRequest = {}): Promise<Response> {
  return send(path, request, "text/event-stream");
}
