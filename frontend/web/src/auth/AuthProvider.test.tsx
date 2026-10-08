import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { MemoryRouter, useLocation } from "react-router";
import { session } from "../api/session";
import { AuthProvider } from "./AuthProvider";
import { useAuth } from "./useAuth";

const env = vi.hoisted(() => ({ local: false }));
vi.mock("../env", () => ({
  get isLocalMode() {
    return env.local;
  },
  cognito: { region: "", userPoolId: "", appClientId: "", domain: "" },
}));

const manager = vi.hoisted(() => ({
  signinRedirect: vi.fn(),
  signinRedirectCallback: vi.fn(),
  signoutRedirect: vi.fn(),
}));
vi.mock("./oidc", () => ({ getUserManager: () => manager }));

const USER = { id: "u1", name: "Ada", email: "ada@example.test", roles: [] };
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const apiError = (status: number, code: string) => json(status, { error: { code, message: "m", retryable: false } });

const fetchMock = vi.fn<typeof fetch>();

function Probe() {
  const { state, signIn, signOut, retry } = useAuth();
  const location = useLocation();
  return (
    <>
      <span data-testid="status">{state.status}</span>
      <span data-testid="detail">
        {state.status === "anonymous" && `signInError=${state.signInError}`}
        {state.status === "failed" && state.reason}
        {(state.status === "authenticated" || state.status === "local") && state.user.name}
      </span>
      <span data-testid="path">{location.pathname}</span>
      <button onClick={() => void signIn("/items")}>sign in</button>
      <button onClick={signOut}>sign out</button>
      <button onClick={retry}>retry</button>
    </>
  );
}

const mount = (strict = false) => {
  const tree = (
    <MemoryRouter>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </MemoryRouter>
  );
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
};
const status = () => screen.getByTestId("status").textContent;
const calledPaths = () => fetchMock.mock.calls.map(([url]) => String(url));

beforeEach(() => {
  env.local = false;
  fetchMock.mockReset();
  manager.signinRedirect.mockReset();
  manager.signinRedirectCallback.mockReset();
  manager.signoutRedirect.mockReset().mockResolvedValue(undefined);
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState({}, "", "/");
});

describe("with an identity provider", () => {
  test("no token: anonymous, without calling the API", async () => {
    mount();
    await waitFor(() => expect(status()).toBe("anonymous"));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("detail")).toHaveTextContent("signInError=false");
  });

  test("a stored token is rehydrated into a session", async () => {
    session.setToken("tok");
    fetchMock.mockResolvedValue(json(200, USER));
    mount();
    await waitFor(() => expect(status()).toBe("authenticated"));
    expect(screen.getByTestId("detail")).toHaveTextContent("Ada");
  });

  test("a rejected token is discarded", async () => {
    session.setToken("stale");
    fetchMock.mockResolvedValue(apiError(401, "auth_invalid_token"));
    mount();
    await waitFor(() => expect(status()).toBe("anonymous"));
    expect(session.getToken()).toBeNull();
  });

  test("a failure that is not a 401 keeps the token and can be retried", async () => {
    session.setToken("tok");
    fetchMock.mockResolvedValueOnce(new Response("", { status: 503 })).mockResolvedValueOnce(json(200, USER));
    mount();
    await waitFor(() => expect(status()).toBe("failed"));
    expect(screen.getByTestId("detail")).toHaveTextContent("request");
    expect(session.getToken()).toBe("tok");
    await userEvent.click(screen.getByText("retry"));
    await waitFor(() => expect(status()).toBe("authenticated"));
  });

  test("sign-in starts the redirect and remembers the destination", async () => {
    mount();
    await waitFor(() => expect(status()).toBe("anonymous"));
    await userEvent.click(screen.getByText("sign in"));
    expect(manager.signinRedirect).toHaveBeenCalledWith({ state: { returnTo: "/items" } });
  });

  test("a returning authorization is exchanged exactly once, even under StrictMode, and leaves the URL", async () => {
    window.history.replaceState({}, "", "/?code=abc&state=xyz");
    manager.signinRedirectCallback.mockResolvedValue({ id_token: "idt", state: { returnTo: "/items" } });
    fetchMock.mockResolvedValue(json(200, { access_token: "app-tok", user: USER }));
    mount(true);
    await waitFor(() => expect(status()).toBe("authenticated"));

    expect(manager.signinRedirectCallback).toHaveBeenCalledOnce();
    expect(manager.signinRedirectCallback.mock.calls[0][0]).toContain("code=abc");
    expect(calledPaths()).toEqual(["/auth/login"]);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ id_token: "idt" });
    expect(session.getToken()).toBe("app-tok");
    expect(window.location.search).toBe("");
    expect(screen.getByTestId("path")).toHaveTextContent("/items");
  });

  test("an off-origin destination in the state is ignored", async () => {
    window.history.replaceState({}, "", "/?code=abc&state=xyz");
    manager.signinRedirectCallback.mockResolvedValue({ id_token: "idt", state: { returnTo: "//evil.test" } });
    fetchMock.mockResolvedValue(json(200, { access_token: "t", user: USER }));
    mount();
    await waitFor(() => expect(status()).toBe("authenticated"));
    expect(screen.getByTestId("path")).toHaveTextContent("/");
  });

  test("a provider error shows a flag, never the provider's text", async () => {
    window.history.replaceState({}, "", "/?error=access_denied&error_description=secret+detail");
    mount();
    await waitFor(() => expect(status()).toBe("anonymous"));
    expect(screen.getByTestId("detail")).toHaveTextContent("signInError=true");
    expect(document.body).not.toHaveTextContent("secret");
    expect(window.location.search).toBe("");
    expect(manager.signinRedirectCallback).not.toHaveBeenCalled();
  });

  test("a rejected token exchange is a sign-in error and stores no token", async () => {
    window.history.replaceState({}, "", "/?code=abc&state=xyz");
    manager.signinRedirectCallback.mockResolvedValue({ id_token: "idt" });
    fetchMock.mockResolvedValue(apiError(401, "auth_invalid_token"));
    mount();
    await waitFor(() => expect(status()).toBe("anonymous"));
    expect(screen.getByTestId("detail")).toHaveTextContent("signInError=true");
    expect(session.getToken()).toBeNull();
  });

  test("sign-out drops the token and ends the provider session", async () => {
    session.setToken("tok");
    fetchMock.mockResolvedValue(json(200, USER));
    mount();
    await waitFor(() => expect(status()).toBe("authenticated"));
    await userEvent.click(screen.getByText("sign out"));
    expect(session.getToken()).toBeNull();
    expect(status()).toBe("anonymous");
    expect(manager.signoutRedirect).toHaveBeenCalledOnce();
  });

  test("a 401 on a later request ends the session", async () => {
    session.setToken("tok");
    fetchMock.mockResolvedValue(json(200, USER));
    mount();
    await waitFor(() => expect(status()).toBe("authenticated"));
    act(() => session.notifyUnauthorized());
    expect(status()).toBe("anonymous");
    expect(session.getToken()).toBeNull();
  });
});

describe("local mode", () => {
  beforeEach(() => {
    env.local = true;
  });

  test("takes the user the API returns and never touches the identity provider", async () => {
    fetchMock.mockResolvedValue(json(200, USER));
    mount();
    await waitFor(() => expect(status()).toBe("local"));
    expect(screen.getByTestId("detail")).toHaveTextContent("Ada");
    expect(calledPaths()).toEqual(["/auth/me"]);
    expect(manager.signinRedirect).not.toHaveBeenCalled();
  });

  test("a 401 means the backend bypass is missing, not a redirect", async () => {
    fetchMock.mockResolvedValue(apiError(401, "auth_invalid_token"));
    mount();
    await waitFor(() => expect(status()).toBe("failed"));
    expect(screen.getByTestId("detail")).toHaveTextContent("bypassMissing");
  });

  test("an unreachable API is a request failure", async () => {
    fetchMock.mockResolvedValue(new Response("", { status: 503 }));
    mount();
    await waitFor(() => expect(status()).toBe("failed"));
    expect(screen.getByTestId("detail")).toHaveTextContent("request");
  });

  test("a later 401 turns the session into the bypass message", async () => {
    fetchMock.mockResolvedValue(json(200, USER));
    mount();
    await waitFor(() => expect(status()).toBe("local"));
    act(() => session.notifyUnauthorized());
    expect(screen.getByTestId("detail")).toHaveTextContent("bypassMissing");
  });

  test("sign-out does nothing", async () => {
    fetchMock.mockResolvedValue(json(200, USER));
    mount();
    await waitFor(() => expect(status()).toBe("local"));
    await userEvent.click(screen.getByText("sign out"));
    expect(status()).toBe("local");
    expect(manager.signoutRedirect).not.toHaveBeenCalled();
  });
});
