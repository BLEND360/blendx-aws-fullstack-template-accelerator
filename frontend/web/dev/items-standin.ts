/** Test double for the items API (/api/v1/items, shipped by ST-05). The page tests route fetch
 * through it so they exercise the contract without a server; the dev server no longer uses it
 * and proxies to the real API.
 *
 * Creating an item named "error" fails with a retryable 503; an empty name (or one over 80
 * characters) fails with per-field 422 errors. */

export interface StoredItem {
  id: string;
  name: string;
  description: string | null;
  createdAt: string;
}

export interface StandInRequest {
  method: string;
  body: unknown;
  /** The item addressed by /api/v1/items/{id}; absent for the collection. */
  id?: string;
}

export interface StandInResponse {
  status: number;
  body: unknown;
}

const NAME_MAX = 80;
const DESCRIPTION_MAX = 280;

let counter = 0;
let nextId = 0; // ids stay unique after a delete

function failure(status: number, code: string, message: string, retryable: boolean, fields?: object[]): StandInResponse {
  return { status, body: { error: { code, message, retryable, requestId: `standin-${++counter}`, ...(fields && { fields }) } } };
}

function validate(input: Record<string, unknown>): { name: string; description: string | null } | { fields: object[] } {
  const name = typeof input.name === "string" ? input.name.trim() : "";
  const description = typeof input.description === "string" && input.description.trim() ? input.description.trim() : null;
  const fields: object[] = [];
  if (!name) fields.push({ location: "body.name", message: "Name is required." });
  else if (name.length > NAME_MAX) fields.push({ location: "body.name", message: `Name must be at most ${NAME_MAX} characters.` });
  if (description && description.length > DESCRIPTION_MAX) {
    fields.push({ location: "body.description", message: `Description must be at most ${DESCRIPTION_MAX} characters.` });
  }
  return fields.length ? { fields } : { name, description };
}

const notFound = () => failure(404, "not_found", "Item not found.", false);

export function handleItems(request: StandInRequest, store: StoredItem[]): StandInResponse {
  if (request.id !== undefined) {
    const index = store.findIndex((i) => i.id === request.id);
    if (index < 0) return notFound();
    if (request.method === "GET") return { status: 200, body: store[index] };
    if (request.method === "DELETE") {
      store.splice(index, 1);
      return { status: 204, body: undefined };
    }
    if (request.method !== "PATCH") return failure(405, "method_not_allowed", "Method Not Allowed", false);
    const edited = validate(asRecord(request.body));
    if ("fields" in edited) return failure(422, "validation_error", "The request payload is not valid.", false, edited.fields);
    store[index] = { ...store[index], ...edited };
    return { status: 200, body: store[index] };
  }

  if (request.method === "GET") return { status: 200, body: { items: [...store].reverse() } };
  if (request.method !== "POST") return failure(405, "method_not_allowed", "Method Not Allowed", false);

  const input = asRecord(request.body);
  const created = validate(input);
  if ("fields" in created) return failure(422, "validation_error", "The request payload is not valid.", false, created.fields);
  if (created.name === "error") return failure(503, "data_unavailable", "The data store is temporarily unavailable.", true);

  const item: StoredItem = { id: `item-${++nextId}`, ...created, createdAt: new Date().toISOString() };
  store.push(item);
  return { status: 201, body: item };
}

function asRecord(body: unknown): Record<string, unknown> {
  return typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
}
