import { handleItems } from "../dev/items-standin";
import type { StoredItem } from "../dev/items-standin";

const post = (body: unknown) => ({ method: "POST", body });
const fresh = (): StoredItem[] => [];

test("an empty store lists nothing", () => {
  expect(handleItems({ method: "GET", body: undefined }, fresh())).toEqual({ status: 200, body: { items: [] } });
});

test("creating returns 201 and the item, listed newest first", () => {
  const store = fresh();
  const first = handleItems(post({ name: "one", description: "d" }), store);
  expect(first.status).toBe(201);
  expect(first.body).toMatchObject({ name: "one", description: "d" });
  handleItems(post({ name: "two" }), store);
  const list = handleItems({ method: "GET", body: undefined }, store).body as { items: StoredItem[] };
  expect(list.items.map((i) => i.name)).toEqual(["two", "one"]);
  expect(list.items[0].description).toBeNull();
});

test.each([
  ["empty name", { name: "  " }],
  ["missing name", {}],
  ["overlong name", { name: "x".repeat(81) }],
])("%s is a 422 with a field error on body.name", (_label, body) => {
  const result = handleItems(post(body), fresh());
  expect(result.status).toBe(422);
  expect(result.body).toMatchObject({
    error: { code: "validation_error", retryable: false, fields: [{ location: "body.name" }] },
  });
});

test("an overlong description is a field error on body.description", () => {
  const result = handleItems(post({ name: "ok", description: "x".repeat(281) }), fresh());
  expect(result.body).toMatchObject({ error: { fields: [{ location: "body.description" }] } });
});

test('the name "error" is the demonstrable retryable failure and stores nothing', () => {
  const store = fresh();
  const result = handleItems(post({ name: "error" }), store);
  expect(result.status).toBe(503);
  expect(result.body).toMatchObject({ error: { code: "data_unavailable", retryable: true } });
  expect(store).toEqual([]);
});

test("errors carry the template's shape including a request id", () => {
  const { error } = handleItems(post({}), fresh()).body as { error: Record<string, unknown> };
  expect(Object.keys(error).sort()).toEqual(["code", "fields", "message", "requestId", "retryable"]);
});

test("other methods are refused in the same shape", () => {
  expect(handleItems({ method: "DELETE", body: undefined }, fresh()).status).toBe(405);
});
