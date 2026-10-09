import { Alert, Button, Empty, Flex, Typography, theme } from "antd";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ApiErrorAlert } from "../../ui/ApiErrorAlert";
import { LoadingIndicator } from "../../ui/LoadingIndicator";
import { messages, turnErrorMessage } from "../../messages";
import type { ChatItem, TurnFailure } from "./chatState";
import { Composer } from "./Composer";
import { ToolCard } from "./ToolCard";
import { useChat } from "./useChat";
import { useConversation } from "./useConversation";

// Visible to assistive technology only: announcements that must not move the focus or clutter the screen.
const VISUALLY_HIDDEN = { position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)", whiteSpace: "nowrap" } as const;

function Bubble({ item }: { item: Extract<ChatItem, { kind: "user" | "assistant" }> }) {
  const { token } = theme.useToken();
  const mine = item.kind === "user";
  return (
    <Flex justify={mine ? "flex-end" : "flex-start"}>
      <div
        style={{
          maxWidth: "85%",
          padding: `${token.paddingXS}px ${token.paddingSM}px`,
          borderRadius: token.borderRadiusLG,
          background: mine ? token.colorPrimaryBg : token.colorFillQuaternary,
        }}
      >
        <Typography.Text strong type="secondary">
          {mine ? messages.chatYou : messages.chatAssistant}
        </Typography.Text>
        <div style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{item.text}</div>
      </div>
    </Flex>
  );
}

function Failure({ failure, retry, startNew }: { failure: TurnFailure; retry: () => void; startNew: () => void }): ReactNode {
  switch (failure.kind) {
    case "api":
      return <ApiErrorAlert error={failure.error} onRetry={retry} />;
    case "stream":
      return (
        <Alert
          type="error"
          showIcon
          title={turnErrorMessage(failure.code)}
          description={failure.requestId ? `${messages.requestId}: ${failure.requestId}` : undefined}
          action={failure.retryable ? <Button onClick={retry}>{messages.retry}</Button> : undefined}
        />
      );
    case "interrupted":
      return <Alert type="error" showIcon title={messages.chatInterrupted} action={<Button onClick={retry}>{messages.retry}</Button>} />;
    case "sessionGone":
      return <Alert type="warning" showIcon title={messages.chatSessionGone} action={<Button onClick={startNew}>{messages.chatStartNew}</Button>} />;
  }
}

function Conversation(props: { sessionId: string; history: ChatItem[]; forget: () => void; startNew: () => void }) {
  const { token } = theme.useToken();
  const { state, send, retry } = useChat(props.sessionId, props.history, props.forget);
  const streaming = state.turn.phase === "streaming";
  const bottom = useRef<HTMLDivElement>(null);

  // Keep the newest text in view as it grows.
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: "end" });
  }, [state.items, state.turn]);

  // "Responding" while a turn runs, "Response complete" when it ends well; a failure announces itself as an alert.
  const [announcement, setAnnouncement] = useState("");
  const wasStreaming = useRef(false);
  useEffect(() => {
    if (streaming) setAnnouncement(messages.chatResponding);
    else if (wasStreaming.current) setAnnouncement(state.turn.phase === "idle" ? messages.chatResponseComplete : "");
    wasStreaming.current = streaming;
  }, [streaming, state.turn.phase]);

  return (
    <>
      <div role="status" aria-live="polite" style={VISUALLY_HIDDEN}>
        {announcement}
      </div>
      <Flex vertical gap="small" role="log" aria-live="off" aria-busy={streaming} aria-label={messages.chatTitle}>
        {state.items.length === 0 && !streaming && <Empty description={messages.chatEmpty} />}
        {state.items.map((item) =>
          item.kind === "tool" ? <ToolCard key={item.callId} item={item} /> : <Bubble key={item.id} item={item} />,
        )}
        {streaming && <Typography.Text type="secondary">{messages.chatResponding}…</Typography.Text>}
        {state.turn.phase === "failed" && <Failure failure={state.turn.failure} retry={retry} startNew={props.startNew} />}
        <div ref={bottom} />
      </Flex>
      <div style={{ position: "sticky", bottom: 0, paddingBlock: token.paddingSM, background: token.colorBgBase }}>
        <Composer disabled={streaming} onSend={send} />
      </div>
    </>
  );
}

export interface ChatPageProps {
  /** The API is answering with recorded responses (a demonstration). */
  replayMode: boolean;
}

export function ChatPage({ replayMode }: ChatPageProps) {
  const { state, forget, startNew, reload } = useConversation();
  return (
    <Flex vertical gap="middle" style={{ maxWidth: 800, marginInline: "auto" }}>
      <Flex align="center" justify="space-between" gap="small">
        <Typography.Title level={2} style={{ margin: 0 }}>
          {messages.chatTitle}
        </Typography.Title>
        <Button onClick={startNew}>{messages.chatNewConversation}</Button>
      </Flex>
      {replayMode && <Alert type="info" showIcon title={messages.chatReplayNotice} />}
      {state.status === "loading" && <LoadingIndicator />}
      {state.status === "error" && <ApiErrorAlert error={state.error} onRetry={reload} forceRetry />}
      {state.status === "ready" ? (
        <Conversation key={state.sessionId} sessionId={state.sessionId} history={state.history} forget={forget} startNew={startNew} />
      ) : (
        <Composer disabled onSend={() => {}} /> // loading or failed: nothing can be sent yet
      )}
    </Flex>
  );
}
