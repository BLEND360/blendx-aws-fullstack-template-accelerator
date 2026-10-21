import { SendOutlined } from "@ant-design/icons";
import { Button, Flex, Input, Typography } from "antd";
import type { TextAreaRef } from "antd/es/input/TextArea";
import { useEffect, useRef, useState } from "react";
import { messages } from "../../messages";
import { MAX_MESSAGE_CHARS } from "./chatState";

// The counter only appears when it starts to matter.
const SHOW_COUNTER_FROM = Math.floor(MAX_MESSAGE_CHARS * 0.8);

export interface ComposerProps {
  /** The conversation is loading or a turn is running: typing is fine, sending is not. */
  disabled: boolean;
  onSend: (text: string) => void;
}

export function Composer({ disabled, onSend }: ComposerProps) {
  const [value, setValue] = useState("");
  const input = useRef<TextAreaRef>(null);

  // Ready again (the conversation loaded, or a turn ended in any way): the cursor is back in the field.
  useEffect(() => {
    if (!disabled) input.current?.focus();
  }, [disabled]);

  const tooLong = value.length > MAX_MESSAGE_CHARS;
  const canSend = !disabled && value.trim().length > 0 && !tooLong;

  const submit = () => {
    if (!canSend) return;
    onSend(value);
    setValue("");
  };

  return (
    <Flex vertical gap={4}>
      <div className={`chat-composer${tooLong ? " chat-composer--error" : ""}`}>
        <Input.TextArea
          ref={input}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onPressEnter={(e) => {
            // Shift+Enter is a new line; Enter sends. A key pressed while composing text (IME) is not a send.
            if (e.shiftKey || e.nativeEvent.isComposing) return;
            e.preventDefault();
            submit();
          }}
          aria-label={messages.chatMessageLabel}
          aria-describedby={tooLong ? "composer-too-long" : undefined}
          aria-invalid={tooLong || undefined}
          placeholder={messages.chatPlaceholder}
          autoSize={{ minRows: 1, maxRows: 6 }}
          variant="borderless"
        />
        <Button type="primary" shape="circle" icon={<SendOutlined />} aria-label={messages.chatSend} onClick={submit} disabled={!canSend} />
      </div>
      {tooLong && (
        <Typography.Text id="composer-too-long" type="danger" role="alert">
          {messages.chatTooLong} ({value.length} / {MAX_MESSAGE_CHARS})
        </Typography.Text>
      )}
      {!tooLong && value.length >= SHOW_COUNTER_FROM && (
        <Typography.Text type="secondary">
          {value.length} / {MAX_MESSAGE_CHARS}
        </Typography.Text>
      )}
    </Flex>
  );
}
