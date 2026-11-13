import { Alert } from "antd";
import { Navigate, Outlet, useLocation } from "react-router";
import { messages } from "../messages";
import { ApiErrorAlert } from "../ui/ApiErrorAlert";
import { LoadingIndicator } from "../ui/LoadingIndicator";
import { useAuth } from "./useAuth";

/** Renders the protected routes only once a session exists; says why when it cannot tell. */
export function ProtectedRoute() {
  const { state, retry } = useAuth();
  const location = useLocation();

  switch (state.status) {
    case "resolving":
      return <LoadingIndicator />;
    case "anonymous":
      return (
        <Navigate
          to="/login"
          replace
          state={{ from: `${location.pathname}${location.search}${location.hash}` }}
        />
      );
    case "failed":
      return (
        <div style={{ padding: 24 }}>
          {state.reason === "bypassMissing" ? (
            <Alert type="error" showIcon title={messages.localBypassRequired} />
          ) : (
            <ApiErrorAlert error={state.error} onRetry={retry} forceRetry />
          )}
        </div>
      );
    case "authenticated":
    case "local":
      return <Outlet />;
  }
}
