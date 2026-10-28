import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router";
import { fetchCurrentUser, loginWithIdToken } from "../api/auth";
import { ApiError, asApiError } from "../api/client";
import { field } from "../api/guards";
import { session } from "../api/session";
import { isLocalMode } from "../env";
import { messages } from "../messages";
import { getUserManager } from "./oidc";
import { safeReturnTo } from "./returnTo";
import { AuthContext } from "./useAuth";
import type { AuthContextValue, AuthState } from "./useAuth";

const anonymous = (signInError: boolean): AuthState => ({ status: "anonymous", signInError });

const bypassMissing = (): AuthState => ({
  status: "failed",
  reason: "bypassMissing",
  error: new ApiError({
    status: 401,
    code: "auth_invalid_token",
    message: messages.localBypassRequired,
    retryable: false,
  }),
});

/** The response is single-use: take it off the URL before anything can reload it. */
function stripAuthParams(): void {
  window.history.replaceState({}, "", window.location.pathname);
}

/** Works out who the user is (existing token, sign-in redirect, or local bypass) and exposes it. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [state, setState] = useState<AuthState>({ status: "resolving" });
  const stateRef = useRef(state);
  stateRef.current = state;
  // StrictMode runs the mount effect twice; the redirect response can be consumed once.
  const started = useRef(false);

  const loadUser = useCallback(async (kind: "authenticated" | "local") => {
    try {
      const user = await fetchCurrentUser();
      setState({ status: kind, user });
    } catch (error) {
      const apiError = asApiError(error);
      if (apiError.status === 401) {
        if (kind === "local") {
          setState(bypassMissing());
        } else {
          session.setToken(null);
          setState(anonymous(false));
        }
      } else {
        setState({ status: "failed", error: apiError, reason: "request" });
      }
    }
  }, []);

  const completeSignIn = useCallback(
    async (callbackUrl: string) => {
      try {
        const oidcUser = await getUserManager().signinRedirectCallback(callbackUrl);
        if (!oidcUser.id_token) throw new Error("no id token");
        const { access_token, user } = await loginWithIdToken(oidcUser.id_token);
        session.setToken(access_token);
        setState({ status: "authenticated", user });
        navigate(safeReturnTo(field(oidcUser.state, "returnTo")), { replace: true });
      } catch {
        // The provider's own text is deliberately dropped.
        setState(anonymous(true));
      }
    },
    [navigate],
  );

  const resolve = useCallback(
    async (initial: boolean) => {
      const params = new URLSearchParams(window.location.search);
      if (initial && !isLocalMode && params.has("error")) {
        stripAuthParams();
        setState(anonymous(true));
      } else if (initial && !isLocalMode && params.has("code") && params.has("state")) {
        const callbackUrl = window.location.href;
        stripAuthParams();
        await completeSignIn(callbackUrl);
      } else if (isLocalMode) {
        await loadUser("local");
      } else if (session.getToken()) {
        await loadUser("authenticated");
      } else {
        setState(anonymous(false));
      }
    },
    [completeSignIn, loadUser],
  );

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void resolve(true);
  }, [resolve]);

  // A 401 on any later request means the session is gone.
  useEffect(() => {
    session.onUnauthorized(() => {
      const current = stateRef.current;
      if (current.status === "authenticated") {
        session.setToken(null);
        setState(anonymous(false));
      } else if (current.status === "local") {
        setState(bypassMissing());
      }
    });
    return () => session.onUnauthorized(null);
  }, []);

  const signIn = useCallback(async (returnTo: string) => {
    try {
      await getUserManager().signinRedirect({ state: { returnTo: safeReturnTo(returnTo) } });
    } catch {
      setState(anonymous(true));
    }
  }, []);

  const signOut = useCallback(() => {
    if (isLocalMode) return; // nothing to end
    session.setToken(null);
    setState(anonymous(false));
    getUserManager()
      .signoutRedirect()
      .catch(() => {});
  }, []);

  const retry = useCallback(() => {
    setState({ status: "resolving" });
    void resolve(false);
  }, [resolve]);

  const value = useMemo<AuthContextValue>(() => ({ state, signIn, signOut, retry }), [state, signIn, signOut, retry]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
