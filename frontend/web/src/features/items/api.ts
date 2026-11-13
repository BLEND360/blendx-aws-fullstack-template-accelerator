import { apiFetch } from "../../api/client";

/** The items contract, as ST-05 is expected to fix it. This is the only module
 * that knows it: if ST-05 differs, the change lands here. */
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
