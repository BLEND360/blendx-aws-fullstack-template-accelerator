import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { App } from "../App";
import { AuthProvider } from "../auth/AuthProvider";
import { ThemeModeProvider } from "../theme/ThemeModeProvider";

export const USER = { id: "local-dev-user", name: "Local Dev", email: "local-dev@example.test", roles: [] };
export const CONFIG = { allowedModelIds: ["model-a", "model-b"], defaultModelId: "model-a" };

export const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** Mounts the whole app at `path` with the same providers main.tsx uses. In tests
 * no Cognito variables exist, so the app starts in local mode. */
export function renderApp(path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <ThemeModeProvider>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <AuthProvider>
            <App />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeModeProvider>,
  );
}
