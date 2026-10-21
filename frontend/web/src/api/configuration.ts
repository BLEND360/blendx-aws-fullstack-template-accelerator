import { apiFetch } from "./client";

/** What GET /api/v1/configuration returns: the deployment's display values.
 * The SPA keeps no copy of these; this is their only source. */
export interface ClientConfiguration {
  allowedModelIds: string[];
  defaultModelId: string;
  /** The API is answering with recorded responses (a demonstration), not a real harness. */
  replayMode: boolean;
}

export function fetchConfiguration(signal?: AbortSignal): Promise<ClientConfiguration> {
  return apiFetch<ClientConfiguration>("/api/v1/configuration", { signal });
}
