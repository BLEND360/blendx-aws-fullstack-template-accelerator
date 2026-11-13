import type { ApiError } from "../../api/client";
import type { TurnEvent } from "../../api/events";

/** What the API accepts in one message; the composer and the hook both refuse more. */
export const MAX_MESSAGE_CHARS = 12000;

/** The conversation as one ordered timeline: what was said, and what the agent did in between. */
export type ChatItem =
  | { kind: "user"; id: string; text: string }
  | { kind: "assistant"; id: string; text: string; complete: boolean }
  | {
      kind: "tool";
      callId: string;
      label: string;
      status: "running" | "success" | "error";
      input?: unknown;
      result?: unknown;
    };

export type ToolItem = Extract<ChatItem, { kind: "tool" }>;

export type TurnFailure =
  | { kind: "api"; error: ApiError } // refused before the response started
  | { kind: "stream"; code: string; retryable: boolean; requestId: string | null } // an error event
  | { kind: "interrupted" } // the response stopped without an end
  | { kind: "sessionGone" }; // the conversation does not exist any more

export type TurnState = { phase: "idle" } | { phase: "streaming" } | { phase: "failed"; failure: TurnFailure };

export interface ChatState {
  items: ChatItem[];
  turn: TurnState;
  /** The message of the turn in progress or the one that failed: what a retry sends again. */
  pendingText: string | null;
}

export type ChatAction =
  | { type: "historyLoaded"; items: ChatItem[] }
  | { type: "userSent"; id: string; text: string }
  | { type: "retryStarted" }
  | { type: "event"; event: TurnEvent }
  | { type: "failed"; failure: TurnFailure };

export const emptyChat = (items: ChatItem[] = []): ChatState => ({ items, turn: { phase: "idle" }, pendingText: null });

/** Whatever was being written is now as complete as it will get. */
const closeAssistant = (items: ChatItem[]): ChatItem[] =>
  items.map((item) => (item.kind === "assistant" && !item.complete ? { ...item, complete: true } : item));

function updateTool(items: ChatItem[], callId: string, change: Partial<Extract<ChatItem, { kind: "tool" }>>): ChatItem[] {
  return items.map((item) => (item.kind === "tool" && item.callId === callId ? { ...item, ...change } : item));
}

function applyEvent(state: ChatState, event: TurnEvent): ChatState {
  const { items } = state;
  switch (event.type) {
    case "delta": {
      const last = items.at(-1);
      if (last?.kind === "assistant" && !last.complete) {
        return { ...state, items: [...items.slice(0, -1), { ...last, text: last.text + event.text }] };
      }
      // A tool card between two stretches of text makes the second one a new message.
      return { ...state, items: [...items, { kind: "assistant", id: `assistant-${items.length}`, text: event.text, complete: false }] };
    }
    case "tool_started":
      if (items.some((i) => i.kind === "tool" && i.callId === event.callId)) return state;
      return { ...state, items: [...closeAssistant(items), { kind: "tool", callId: event.callId, label: event.label, status: "running" }] };
    case "tool_input":
      return { ...state, items: updateTool(items, event.callId, { input: event.input }) };
    case "tool_finished":
      return { ...state, items: updateTool(items, event.callId, { status: event.status, result: event.result }) };
    case "done":
      return { ...state, items: closeAssistant(items), turn: { phase: "idle" } };
    case "error":
      return {
        ...state,
        items: closeAssistant(items),
        turn: { phase: "failed", failure: { kind: "stream", code: event.code, retryable: event.retryable, requestId: event.requestId } },
      };
  }
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "historyLoaded":
      return emptyChat(action.items);
    case "userSent":
      return {
        items: [...state.items, { kind: "user", id: action.id, text: action.text }],
        turn: { phase: "streaming" },
        pendingText: action.text,
      };
    case "retryStarted": {
      // The failed attempt's partial answer and cards go; the user's message stays, once.
      const lastUser = state.items.map((i) => i.kind).lastIndexOf("user");
      return { ...state, items: lastUser < 0 ? state.items : state.items.slice(0, lastUser + 1), turn: { phase: "streaming" } };
    }
    case "event":
      // Events only mean something while a turn is running; a late one after the end is dropped.
      return state.turn.phase === "streaming" ? applyEvent(state, action.event) : state;
    case "failed":
      return { ...state, items: closeAssistant(state.items), turn: { phase: "failed", failure: action.failure } };
  }
}
