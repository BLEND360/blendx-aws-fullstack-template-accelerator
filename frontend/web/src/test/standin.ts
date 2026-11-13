import { handleItems } from "../../dev/items-standin";
import type { StoredItem } from "../../dev/items-standin";

/** Routes fetch for /api/v1/items through the same handler the dev server uses,
 * so page tests exercise the contract and not a copy of it. Other paths go to `other`. */
export function itemsFetch(other: (url: string) => Response, store: StoredItem[] = []) {
  return vi.fn<typeof fetch>((input, init) => {
    const url = String(input);
    if (url !== "/api/v1/items") return Promise.resolve(other(url));
    const body = init?.body ? (JSON.parse(String(init.body)) as unknown) : undefined;
    const { status, body: payload } = handleItems({ method: init?.method ?? "GET", body }, store);
    return Promise.resolve(
      new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } }),
    );
  });
}
