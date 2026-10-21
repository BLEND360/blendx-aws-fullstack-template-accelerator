import { Spin } from "antd";
import { messages } from "../messages";

export function LoadingIndicator() {
  return (
    <div role="status" aria-label={messages.loading} style={{ display: "grid", placeItems: "center", padding: 48 }}>
      <Spin size="large" />
    </div>
  );
}
