import { apiFetch } from "../../api/client";

/** The items contract (backend /api/v1/items). This is the only module that knows it. */
export interface Item {
  id: string;
  name: string;
  description: string | null;
  createdAt: string;
}

export interface NewItem {
  name: string;
  description?: string;
}

export async function listItems(signal?: AbortSignal): Promise<Item[]> {
  const { items } = await apiFetch<{ items: Item[] }>("/api/v1/items", { signal });
  return items;
}

export function createItem(input: NewItem): Promise<Item> {
  return apiFetch<Item>("/api/v1/items", { method: "POST", body: input });
}

/** An empty description clears it; the API treats null as "remove". */
export function updateItem(id: string, input: NewItem): Promise<Item> {
  return apiFetch<Item>(`/api/v1/items/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: { name: input.name, description: input.description?.trim() ? input.description : null },
  });
}

export async function deleteItem(id: string): Promise<void> {
  await apiFetch<void>(`/api/v1/items/${encodeURIComponent(id)}`, { method: "DELETE" });
}
