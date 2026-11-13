import { CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined } from "@ant-design/icons";
import { Card, Flex, Tag, Typography, theme } from "antd";
import type { ReactNode } from "react";
import { messages } from "../../messages";
import type { ToolItem } from "./chatState";

const STATUS = {
  running: { text: messages.chatToolRunning, icon: <LoadingOutlined />, color: "processing" },
  success: { text: messages.chatToolDone, icon: <CheckCircleOutlined />, color: "success" },
  error: { text: messages.chatToolFailed, icon: <CloseCircleOutlined />, color: "error" },
} as const;

function Block({ title, value }: { title: string; value: unknown }) {
  const { token } = theme.useToken();
  return (
    <div>
      <Typography.Text type="secondary">{title}</Typography.Text>
      <pre
        style={{
          margin: 0,
          padding: token.paddingXS,
          maxHeight: 160,
          overflow: "auto",
          whiteSpace: "pre-wrap",
          background: token.colorFillQuaternary,
          borderRadius: token.borderRadiusSM,
        }}
      >
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

/** One tool the agent used: its label, where it is (in words and an icon, not only a color), what went in and what came out. */
export function ToolCard({ item }: { item: ToolItem }): ReactNode {
  const status = STATUS[item.status];
  return (
    <Card size="small" role="group" aria-label={`${item.label}: ${status.text}`}>
      <Flex vertical gap="small">
        <Flex align="center" justify="space-between" gap="small">
          <Typography.Text strong>{item.label}</Typography.Text>
          <Tag icon={status.icon} color={status.color}>
            {status.text}
          </Tag>
        </Flex>
        {item.input !== undefined && <Block title={messages.chatToolInput} value={item.input} />}
        {item.result !== undefined && <Block title={messages.chatToolResult} value={item.result} />}
      </Flex>
    </Card>
  );
}
