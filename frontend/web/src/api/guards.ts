export const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null;

/** One property of a value of unknown shape (router state, OIDC state); undefined if it is not an object. */
export const field = (value: unknown, key: string): unknown => (isRecord(value) ? value[key] : undefined);
