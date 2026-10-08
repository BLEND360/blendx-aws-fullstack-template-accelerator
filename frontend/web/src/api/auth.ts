import { apiFetch } from "./client";

/** The auth contract ST-08 owns; consumed here as the MVP defines it. */
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
