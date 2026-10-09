/** Stand-in for the items API until ST-05 ships it. Same origin, same contract:
 * the SPA cannot tell it from the real thing. Delete this file and its line in
 * vite.config.ts when /api/v1/items exists; nothing under src/ changes.
 *
 * Try it: creating an item named "error" fails with a retryable 503; an empty
 * name (or one over 80 characters) fails with per-field 422 errors. */
import type { IncomingMessage } from "node:http";
import type { Plugin } from "vite";

export interface StoredItem {
  id: string;
  name: string;
  description: string | null;
  createdAt: string;
}

export interface StandInRequest {
  method: string;
  body: unknown;
}

export interface StandInResponse {
  status: number;
  body: unknown;
}

const NAME_MAX = 80;
const DESCRIPTION_MAX = 280;

let counter = 0;

function failure(status: number, code: string, message: string, retryable: boolean, fields?: object[]): StandInResponse {
  return { status, body: { error: { code, message, retryable, requestId: `standin-${++counter}`, ...(fields && { fields }) } } };
}

export function handleItems(request: StandInRequest, store: StoredItem[]): StandInResponse {
  if (request.method === "GET") return { status: 200, body: { items: [...store].reverse() } };
  if (request.method !== "POST") return failure(405, "method_not_allowed", "Method Not Allowed", false);

  const input = (typeof request.body === "object" && request.body !== null ? request.body : {}) as Record<string, unknown>;
  const name = typeof input.name === "string" ? input.name.trim() : "";
  const description = typeof input.description === "string" && input.description.trim() ? input.description.trim() : null;

  const fields: object[] = [];
  if (!name) fields.push({ location: "body.name", message: "Name is required." });
  else if (name.length > NAME_MAX) fields.push({ location: "body.name", message: `Name must be at most ${NAME_MAX} characters.` });
  if (description && description.length > DESCRIPTION_MAX) {
    fields.push({ location: "body.description", message: `Description must be at most ${DESCRIPTION_MAX} characters.` });
  }
  if (fields.length) return failure(422, "validation_error", "The request payload is not valid.", false, fields);

  if (name === "error") return failure(503, "data_unavailable", "The data store is temporarily unavailable.", true);

  const item: StoredItem = { id: `item-${store.length + 1}`, name, description, createdAt: new Date().toISOString() };
  store.push(item);
  return { status: 201, body: item };
}

async function readJson(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    return undefined;
  }
}

export function itemsStandIn(): Plugin {
  const store: StoredItem[] = [];
  return {
    name: "items-standin",
    apply: "serve",
    // Registered directly (not in a returned function) so it runs before the proxy.
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (new URL(req.url ?? "", "http://localhost").pathname !== "/api/v1/items") return next();
        const result = handleItems({ method: req.method ?? "GET", body: await readJson(req) }, store);
        res.statusCode = result.status;
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result.body));
      });
    },
  };
}
