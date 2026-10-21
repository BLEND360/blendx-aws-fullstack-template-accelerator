import {
  ClockCircleOutlined,
  FileSearchOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
  RobotOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { Alert, Button, Typography } from "antd";
import "../../ui/design.css";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ApiErrorAlert } from "../../ui/ApiErrorAlert";
import { LoadingIndicator } from "../../ui/LoadingIndicator";
import { messages, turnErrorMessage } from "../../messages";
import type { ChatItem, TurnFailure } from "./chatState";
import { Composer } from "./Composer";
import { ToolCard } from "./ToolCard";
import "./chat.css";
import { useChat } from "./useChat";
import { useConversation } from "./useConversation";

// Visible to assistive technology only: announcements that must not move the focus or clutter the screen.
const VISUALLY_HIDDEN = { position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)", whiteSpace: "nowrap" } as const;

function Bubble({ item, streaming }: { item: Extract<ChatItem, { kind: "user" | "assistant" }>; streaming: boolean }) {
  const mine = item.kind === "user";
  return (
    <div className={`chat-row ${mine ? "chat-row--user" : "chat-row--assistant"}`}>
      {!mine && (
        <span className="chat-avatar" aria-hidden>
          <RobotOutlined />
        </span>
      )}
      <div className={`chat-bubble${streaming ? " chat-bubble--streaming" : ""}`}>
        <span className="chat-author">{mine ? messages.chatYou : messages.chatAssistant}</span>
        <div className="chat-text">{item.text}</div>
      </div>
    </div>
  );
}

const SUGGESTION_ICONS = [<FileSearchOutlined />, <WarningOutlined />, <ClockCircleOutlined />, <QuestionCircleOutlined />];

function Welcome({ disabled, onPick }: { disabled: boolean; onPick: (text: string) => void }) {
  return (
    <div className="chat-welcome">
      <span className="chat-halo" aria-hidden>
        <RobotOutlined />
      </span>
      <h3>{messages.chatEmptyTitle}</h3>
      <p>{messages.chatEmpty}</p>
      <div className="chat-suggestions">
        {messages.chatSuggestions.map((text, index) => (
          <button key={text} type="button" className="chat-suggestion" disabled={disabled} onClick={() => onPick(text)}>
            <span className="chat-suggestion-icon" aria-hidden>
              {SUGGESTION_ICONS[index]}
            </span>
            {text}
          </button>
        ))}
      </div>
    </div>
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

  const last = state.items.length - 1;
  return (
    <>
      <div role="status" aria-live="polite" style={VISUALLY_HIDDEN}>
        {announcement}
      </div>
      <div className="chat-scroll">
        <div className="chat-log" role="log" aria-live="off" aria-busy={streaming} aria-label={messages.chatTitle}>
          {state.items.length === 0 && !streaming && <Welcome disabled={streaming} onPick={send} />}
          {state.items.map((item, index) =>
            item.kind === "tool" ? (
              <ToolCard key={item.callId} item={item} />
            ) : (
              <Bubble key={item.id} item={item} streaming={streaming && index === last && item.kind === "assistant"} />
            ),
          )}
          {streaming && (
            <div className="chat-row chat-row--assistant">
              <span className="chat-avatar" aria-hidden>
                <RobotOutlined />
              </span>
              <span className="chat-typing">
                {messages.chatThinking}
                <span aria-hidden>
                  <i />
                  <i />
                  <i />
                </span>
              </span>
            </div>
          )}
          {state.turn.phase === "failed" && <Failure failure={state.turn.failure} retry={retry} startNew={props.startNew} />}
          <div ref={bottom} className="chat-bottom" />
        </div>
      </div>
      <div className="chat-dock">
        <Composer disabled={streaming} onSend={send} />
        <p className="chat-disclaimer">{messages.chatDisclaimer}</p>
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
    <div className="page chat-page">
      <header className="page-head">
        <div>
          <div className="page-kicker">{messages.chatKicker}</div>
          <Typography.Title level={2} className="page-title">
            {messages.chatHeading}
          </Typography.Title>
          <p className="page-sub">{messages.chatSubtitle}</p>
        </div>
        <div className="chat-actions">
          <span className={`status-pill${replayMode ? " status-pill--demo" : ""}`}>{replayMode ? messages.chatDemo : messages.chatLive}</span>
          <Button icon={<PlusOutlined aria-hidden />} onClick={startNew}>
            {messages.chatNewConversation}
          </Button>
        </div>
      </header>
      {replayMode && <Alert type="info" showIcon title={messages.chatReplayNotice} />}
      {state.status === "error" && <ApiErrorAlert error={state.error} onRetry={reload} forceRetry />}
      <div className="chat-canvas">
        {state.status === "ready" ? (
          <Conversation key={state.sessionId} sessionId={state.sessionId} history={state.history} forget={forget} startNew={startNew} />
        ) : (
          <>
            <div className="chat-scroll">{state.status === "loading" && <LoadingIndicator />}</div>
            <div className="chat-dock">
              <Composer disabled onSend={() => {}} /> {/* loading or failed: nothing can be sent yet */}
              <p className="chat-disclaimer">{messages.chatDisclaimer}</p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
