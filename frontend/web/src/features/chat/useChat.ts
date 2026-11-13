import { useCallback, useEffect, useReducer, useRef } from "react";
import { asApiError } from "../../api/client";
import { streamTurn } from "../../api/turns";
import { MAX_MESSAGE_CHARS, chatReducer, emptyChat } from "./chatState";
import type { ChatItem, ChatState } from "./chatState";

/** One conversation's turns: send a message, follow the answer as it streams, retry a failed turn. */
export function useChat(sessionId: string, initial: ChatItem[], onSessionGone: () => void) {
  const [state, dispatch] = useReducer(chatReducer, initial, emptyChat);
  const stateRef = useRef<ChatState>(state);
  stateRef.current = state;
  const controller = useRef<AbortController | null>(null);
  const counter = useRef(0);

  // Leaving the page (or the conversation) ends the turn: the stream is closed, not left reading.
  useEffect(() => () => controller.current?.abort(), []);

  const run = useCallback(
    async (text: string) => {
      controller.current?.abort();
      const mine = new AbortController();
      controller.current = mine;
      try {
        const end = await streamTurn(sessionId, text, mine.signal, (event) => dispatch({ type: "event", event }));
        if (end === "interrupted") dispatch({ type: "failed", failure: { kind: "interrupted" } });
      } catch (error) {
        if (mine.signal.aborted) return;
        const apiError = asApiError(error);
        if (apiError.status === 404) {
          onSessionGone();
          dispatch({ type: "failed", failure: { kind: "sessionGone" } });
        } else {
          dispatch({ type: "failed", failure: { kind: "api", error: apiError } });
        }
      }
    },
    [sessionId, onSessionGone],
  );

  const send = useCallback(
    (text: string) => {
      if (stateRef.current.turn.phase === "streaming") return;
      if (!text.trim() || text.length > MAX_MESSAGE_CHARS) return;
      dispatch({ type: "userSent", id: `user-${++counter.current}`, text });
      void run(text);
    },
    [run],
  );

  const retry = useCallback(() => {
    const { turn, pendingText } = stateRef.current;
    if (turn.phase !== "failed" || pendingText === null) return;
    dispatch({ type: "retryStarted" });
    void run(pendingText);
  }, [run]);

  return { state, send, retry };
}
