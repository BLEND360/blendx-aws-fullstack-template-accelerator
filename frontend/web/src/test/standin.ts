import { handleItems } from "../../dev/items-standin";
import type { StoredItem } from "../../dev/items-standin";

/** Routes fetch for /api/v1/items through the same handler the dev server uses,
 * so page tests exercise the contract and not a copy of it. Other paths go to `other`. */
export function itemsFetch(other: (url: string) => Response, store: StoredItem[] = []) {
  return vi.fn<typeof fetch>((input, init) => {
    const url = String(input);
    const route = /^\/api\/v1\/items(?:\/([^/]+))?$/.exec(url);
    if (!route) return Promise.resolve(other(url));
    const body = init?.body ? (JSON.parse(String(init.body)) as unknown) : undefined;
    const { status, body: payload } = handleItems({ method: init?.method ?? "GET", body, id: route[1] }, store);
    // A 204 has no body, and the Response constructor refuses one.
    return Promise.resolve(
      status === 204
        ? new Response(null, { status })
        : new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } }),
    );
  });
}
