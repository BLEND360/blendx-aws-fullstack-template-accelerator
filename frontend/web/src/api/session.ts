/** The app's session token and the "the API says the session is invalid" event.
 * Kept outside React so apiFetch can use it and tests can drive it. */

const TOKEN_KEY = "app_token";

let unauthorizedHandler: (() => void) | null = null;

export const session = {
  getToken: (): string | null => sessionStorage.getItem(TOKEN_KEY),
  setToken(token: string | null): void {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  },
  /** One handler: the AuthProvider's. Pass null to unregister. */
  onUnauthorized(handler: (() => void) | null): void {
    unauthorizedHandler = handler;
  },
  notifyUnauthorized(): void {
    unauthorizedHandler?.();
  },
};
