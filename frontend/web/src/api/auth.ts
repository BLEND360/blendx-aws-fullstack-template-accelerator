import { apiFetch } from "./client";

/** Shape of GET /auth/me and POST /auth/login. */
export interface UserProfile {
  id: string;
  name: string;
  email: string;
  roles: string[];
}

interface LoginResponse {
  access_token: string;
  user: UserProfile;
}

export function loginWithIdToken(idToken: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/auth/login", { method: "POST", body: { id_token: idToken } });
}

export function fetchCurrentUser(signal?: AbortSignal): Promise<UserProfile> {
  return apiFetch<UserProfile>("/auth/me", { signal });
}
