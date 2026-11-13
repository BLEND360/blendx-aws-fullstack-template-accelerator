/** Fixed user-facing strings. The UI shows these or an API error's own message,
 * never a response body or a provider's text. */
export const messages = {
  networkError: "The service is unavailable. Check your connection and try again.",
  serviceUnavailable: "The service is not available right now. Try again in a moment.",
  unexpected: "The request could not be completed.",
  signInFailed: "We could not sign you in. Try again or contact your administrator.",
  localMode: "Running without authentication (local mode).",
  localBypassRequired:
    "Local mode needs the backend's authentication bypass. Set LOCAL_AUTH_BYPASS=true in backend/api/.env and restart the API.",
  requestId: "Request ID",
  retry: "Retry",
  loading: "Loading",
  signInTitle: "Sign in",
  signInButton: "Sign in",
  signOut: "Sign out",
  darkMode: "Dark mode",
  navHome: "Home",
  navItems: "Items",
  notFoundTitle: "Page not found",
  notFoundLink: "Back to home",
  homeTitle: "Welcome",
  modelsTitle: "Available models",
  defaultModel: "default",
  itemsTitle: "Items",
  itemsEmpty: "No items yet. Create your first one.",
  itemName: "Name",
  itemDescription: "Description",
  itemAdd: "Add item",
  navChat: "Chat",
  chatTitle: "Chat",
  chatEmpty: "Say hello to start the conversation.",
  chatMessageLabel: "Message",
  chatPlaceholder: "Write a message",
  chatSend: "Send",
  chatTooLong: "This message is too long to send.",
  chatNewConversation: "New conversation",
  chatStartNew: "Start a new conversation",
  chatSessionGone: "This conversation no longer exists.",
  chatInterrupted: "The response was interrupted.",
  chatResponding: "The assistant is responding",
  chatResponseComplete: "Response complete",
  chatReplayNotice: "Demo mode: these responses are recorded, not live.",
  chatYou: "You",
  chatAssistant: "Assistant",
  chatToolRunning: "Running",
  chatToolDone: "Done",
  chatToolFailed: "Failed",
  chatToolInput: "Input",
  chatToolResult: "Result",
} as const;

/** What the user reads when a turn ends in an error event. The event carries a code and no text, so
 * these sentences are ours; nothing the server sends is ever shown in their place. */
export const turnErrorMessages: Readonly<Record<string, string>> = {
  harness_unavailable: "The assistant is temporarily unavailable.",
  harness_throttled: "The assistant is busy. Try again in a moment.",
  harness_misconfigured: "No assistant is configured for this deployment.",
  harness_invalid_request: "The assistant could not process this request.",
  tool_failed: "A tool failed while the assistant was answering.",
  memory_unavailable: "Conversation history is temporarily unavailable.",
  memory_throttled: "Conversation history is busy. Try again in a moment.",
  memory_misconfigured: "Conversation history is not set up for this deployment.",
  data_unavailable: "The data store is temporarily unavailable.",
  data_throttled: "The data store is busy. Try again in a moment.",
};

export const turnErrorFallback = "The response could not be completed.";

export function turnErrorMessage(code: string): string {
  return Object.hasOwn(turnErrorMessages, code) ? turnErrorMessages[code] : turnErrorFallback;
}
