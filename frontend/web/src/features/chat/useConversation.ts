import { useCallback, useEffect, useState } from "react";
import { ApiError, asApiError } from "../../api/client";
import { createSession, fetchHistory } from "../../api/sessions";
import type { HistoryMessage } from "../../api/sessions";
import type { ChatItem } from "./chatState";

/** The one conversation this browser keeps. The id is opaque and gives no access by itself:
 * the API only answers for the signed-in user who owns it. */
const STORAGE_KEY = "chat.sessionId";

export type ConversationState =
  | { status: "loading" }
  | { status: "ready"; sessionId: string; history: ChatItem[] }
  | { status: "error"; error: ApiError };

const toItem = (message: HistoryMessage, index: number): ChatItem =>
  message.role === "user"
    ? { kind: "user", id: `history-${index}`, text: message.text }
    : { kind: "assistant", id: `history-${index}`, text: message.text, complete: true };

interface Opened {
  sessionId: string;
  history: ChatItem[];
}

async function openConversation(): Promise<Opened> {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored) {
    try {
      return { sessionId: stored, history: (await fetchHistory(stored)).map(toItem) };
    } catch (error) {
      // Gone (the API restarted) or someone else's (another user signed in here): both are a 404, and both mean start over.
      if (!(error instanceof ApiError && error.status === 404)) throw error;
      localStorage.removeItem(STORAGE_KEY);
    }
  }
  const { id } = await createSession();
  localStorage.setItem(STORAGE_KEY, id);
  return { sessionId: id, history: [] };
}

// React StrictMode runs an effect twice in development; both runs share one opening (module-level,
// so it outlives the effect run that started it), so the page does not create two conversations.
let opening: Promise<Opened> | null = null;
function shared(): Promise<Opened> {
  opening ??= openConversation().finally(() => {
    opening = null;
  });
  return opening;
}

export function useConversation() {
  const [state, setState] = useState<ConversationState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    setState({ status: "loading" });
    shared().then(
      (opened) => {
        if (current) setState({ status: "ready", ...opened });
      },
      (error: unknown) => {
        if (current) setState({ status: "error", error: asApiError(error) });
      },
    );
    return () => {
      current = false;
    };
  }, [attempt]);

  /** Forget the remembered conversation without opening another (it no longer exists). */
  const forget = useCallback(() => localStorage.removeItem(STORAGE_KEY), []);
  /** Leave the current conversation and open a new empty one. */
  const startNew = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setAttempt((n) => n + 1);
  }, []);
  /** Try again after a failure, keeping whatever was remembered. */
  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  return { state, forget, startNew, reload };
}
