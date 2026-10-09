import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { AuthContext } from "../auth/useAuth";
import { ThemeModeProvider } from "../theme/ThemeModeProvider";
import { AppShell } from "./AppShell";

test("a signed-in user sees their name and can sign out; there is no local-mode banner", async () => {
  const signOut = vi.fn();
  render(
    <ThemeModeProvider>
      <AuthContext.Provider
        value={{
          state: { status: "authenticated", user: { id: "u", name: "Ada", email: "a@example.test", roles: [] } },
          signIn: vi.fn(),
          signOut,
          retry: vi.fn(),
        }}
      >
        <MemoryRouter>
          <AppShell />
        </MemoryRouter>
      </AuthContext.Provider>
    </ThemeModeProvider>,
  );
  expect(screen.getByText("Ada")).toBeInTheDocument();
  expect(screen.queryByText(/local mode/i)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(signOut).toHaveBeenCalledOnce();
});
