import { apiFetch } from "./client";

export interface HistoryMessage {
  role: "user" | "assistant";
  text: string;
  createdAt: string;
}

/** A new, empty conversation. Everything about it (owner, memory, model) is decided by the server. */
export async function createSession(): Promise<{ id: string }> {
  const { id } = await apiFetch<{ id: string }>("/api/v1/sessions", { method: "POST", body: {} });
  return { id };
}

export async function fetchHistory(sessionId: string, signal?: AbortSignal): Promise<HistoryMessage[]> {
  const { messages } = await apiFetch<{ messages: HistoryMessage[] }>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/messages`,
    { signal },
  );
  return messages;
}
