import { Alert, Button } from "antd";
import type { ApiError } from "../api/client";
import { messages } from "../messages";

export interface ApiErrorAlertProps {
  error: ApiError;
  onRetry?: () => void;
  /** Offer retry even when the error is not marked retryable: for idempotent reads such as the configuration. */
  forceRetry?: boolean;
}

/** The one way an API failure reaches the user: its message and request id, never a body. */
export function ApiErrorAlert({ error, onRetry, forceRetry = false }: ApiErrorAlertProps) {
  const canRetry = onRetry !== undefined && (error.retryable || forceRetry);
  return (
    <Alert
      type="error"
      showIcon
      title={error.message}
      description={error.requestId ? `${messages.requestId}: ${error.requestId}` : undefined}
      action={canRetry ? <Button onClick={onRetry}>{messages.retry}</Button> : undefined}
    />
  );
}
