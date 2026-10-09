import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { AuthContext } from "../auth/useAuth";
import { Login } from "../pages/Login";
import { itemsFetch } from "../test/standin";
import { CONFIG, USER, json, renderApp } from "../test/render";
import { ThemeModeProvider } from "./ThemeModeProvider";

// What a user can read or hear. File names in asset URLs are not that, so img src is not read.
function userFacingText(): string {
  const attributes = [...document.body.querySelectorAll("[alt],[title],[aria-label],[placeholder]")].flatMap((el) =>
    ["alt", "title", "aria-label", "placeholder"].map((a) => el.getAttribute(a) ?? ""),
  );
  return [document.title, document.body.textContent ?? "", ...attributes].join("\n");
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    itemsFetch((url) => (url === "/auth/me" ? json(200, USER) : url === "/api/v1/configuration" ? json(200, CONFIG) : json(404, {}))),
  );
});

test.each([
  ["/", "Welcome"],
  ["/items", "No items yet. Create your first one."],
  ["/nowhere", "Page not found"],
])("the page at %s names no brand", async (path, loaded) => {
  renderApp(path);
  await screen.findByText(loaded);
  expect(userFacingText()).not.toMatch(/blend/i);
});

test("the sign-in page names no brand", () => {
  render(
    <ThemeModeProvider>
      <AuthContext.Provider
        value={{ state: { status: "anonymous", signInError: true }, signIn: vi.fn(), signOut: vi.fn(), retry: vi.fn() }}
      >
        <MemoryRouter>
          <Login />
        </MemoryRouter>
      </AuthContext.Provider>
    </ThemeModeProvider>,
  );
  expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  expect(userFacingText()).not.toMatch(/blend/i);
});
