import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { ApiError } from "../api/client";
import { Login } from "../pages/Login";
import { ThemeModeProvider } from "../theme/ThemeModeProvider";
import { ProtectedRoute } from "./ProtectedRoute";
import { AuthContext } from "./useAuth";
import type { AuthContextValue, AuthState } from "./useAuth";

const USER = { id: "u", name: "Ada", email: "a@example.test", roles: [] };

function Where() {
  const location = useLocation();
  return <span data-testid="where">{`${location.pathname}|${JSON.stringify(location.state)}`}</span>;
}

function renderAt(path: string, state: AuthState, overrides: Partial<AuthContextValue> = {}) {
  const value: AuthContextValue = {
    state,
    signIn: vi.fn().mockResolvedValue(undefined),
    signOut: vi.fn(),
    retry: vi.fn(),
    ...overrides,
  };
  const wrap = (node: ReactNode) => (
    <ThemeModeProvider>
      <AuthContext.Provider value={value}>
        <MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>
      </AuthContext.Provider>
    </ThemeModeProvider>
  );
  render(
    wrap(
      <>
        <Where />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/secret" element={<p>secret content</p>} />
          </Route>
        </Routes>
      </>,
    ),
  );
  return value;
}

describe("ProtectedRoute", () => {
  test("while resolving it shows a loader and neither content nor a redirect", () => {
    renderAt("/secret", { status: "resolving" });
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(screen.queryByText("secret content")).not.toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/secret|");
  });

  test("without a session it goes to login remembering the requested page", () => {
    renderAt("/secret?tab=1", { status: "anonymous", signInError: false });
    expect(screen.queryByText("secret content")).not.toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent('/login|{"from":"/secret?tab=1"}');
  });

  test.each(["authenticated", "local"] as const)("a %s session sees the content", (status) => {
    renderAt("/secret", { status, user: USER });
    expect(screen.getByText("secret content")).toBeInTheDocument();
  });

  test("a failed attempt shows the error with a forced retry", async () => {
    const error = new ApiError({ status: 503, code: "service_unavailable", message: "Service down.", retryable: false });
    const value = renderAt("/secret", { status: "failed", error, reason: "request" });
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(value.retry).toHaveBeenCalledOnce();
    expect(screen.queryByText("secret content")).not.toBeInTheDocument();
  });

  test("local mode without the backend bypass explains it instead of redirecting", () => {
    const error = new ApiError({ status: 401, code: "auth_invalid_token", message: "x", retryable: false });
    renderAt("/secret", { status: "failed", error, reason: "bypassMissing" });
    expect(screen.getByText(/LOCAL_AUTH_BYPASS=true/)).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/secret|");
  });
});

describe("Login", () => {
  test("the button starts sign-in towards the remembered page", async () => {
    const value = renderAt("/login", { status: "anonymous", signInError: false });
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(value.signIn).toHaveBeenCalledWith("/");
  });

  test("a sign-in error shows the fixed message", () => {
    renderAt("/login", { status: "anonymous", signInError: true });
    expect(screen.getByText(/We could not sign you in/)).toBeInTheDocument();
  });

  test("with a session it sends the user on", () => {
    renderAt("/login", { status: "authenticated", user: USER });
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/(?!login)/);
  });
});
