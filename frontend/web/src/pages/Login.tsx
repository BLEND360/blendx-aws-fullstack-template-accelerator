import { Alert, Button, Card, Flex, Typography } from "antd";
import { Navigate, useLocation } from "react-router";
import { field } from "../api/guards";
import { safeReturnTo } from "../auth/returnTo";
import { useAuth } from "../auth/useAuth";
import { messages } from "../messages";
import { useThemeMode } from "../theme/ThemeModeProvider";
import { BrandLogo } from "../tokens";
import "../ui/design.css";
import { LoadingIndicator } from "../ui/LoadingIndicator";

export function Login() {
  const { state, signIn } = useAuth();
  const { mode } = useThemeMode();
  const from = safeReturnTo(field(useLocation().state, "from"));

  if (state.status === "resolving") return <LoadingIndicator />;
  // Anything but "anonymous" is not a sign-in problem; the protected routes explain it.
  if (state.status !== "anonymous") return <Navigate to={from} replace />;

  return (
    <Flex justify="center" className="login-page">
      <Card className="login-card">
        <Flex vertical align="center" gap="large">
          <BrandLogo height={48} mode={mode} />
          <Typography.Title level={3} className="login-title">
            {messages.signInTitle}
          </Typography.Title>
          {state.signInError && <Alert type="error" showIcon title={messages.signInFailed} style={{ width: "100%" }} />}
          <Button type="primary" size="large" block onClick={() => void signIn(from)}>
            {messages.signInButton}
          </Button>
        </Flex>
      </Card>
    </Flex>
  );
}
