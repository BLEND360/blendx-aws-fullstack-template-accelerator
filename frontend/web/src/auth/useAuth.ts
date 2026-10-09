import { createContext, useContext } from "react";
import type { UserProfile } from "../api/auth";
import type { ApiError } from "../api/client";

export type AuthState =
  | { status: "resolving" }
  | { status: "anonymous"; signInError: boolean }
  | { status: "authenticated"; user: UserProfile }
  | { status: "local"; user: UserProfile }
  | { status: "failed"; error: ApiError; reason: "request" | "bypassMissing" };

export interface AuthContextValue {
  state: AuthState;
  /** Starts the PKCE redirect; `returnTo` is where the user lands afterwards. */
  signIn(returnTo: string): Promise<void>;
  signOut(): void;
  /** Resolve the session again after a failed attempt. */
  retry(): void;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}
