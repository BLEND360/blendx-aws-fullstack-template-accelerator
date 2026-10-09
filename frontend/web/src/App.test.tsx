import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, renderApp, CONFIG, USER } from "./test/render";

const fetchMock = vi.fn<typeof fetch>();

function api(overrides: Record<string, () => Response> = {}) {
  const routes: Record<string, () => Response> = {
    "/auth/me": () => json(200, USER),
    "/api/v1/configuration": () => json(200, CONFIG),
    ...overrides,
  };
  fetchMock.mockImplementation((url) => Promise.resolve(routes[String(url)]?.() ?? json(404, { error: { code: "not_found", message: "Not found." } })));
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.matchMedia = ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
});

test("opening a page URL directly shows that page, with the persistent navigation", async () => {
  api();
  renderApp("/");
  expect(await screen.findByRole("heading", { name: "Welcome" })).toBeInTheDocument();
  expect(within(screen.getByRole("menu")).getByText("Home")).toBeInTheDocument();
});

test("the items page is reachable by URL and from the menu", async () => {
  api({ "/api/v1/items": () => json(200, { items: [] }) });
  renderApp("/items");
  expect(await screen.findByRole("heading", { name: "Items" })).toBeInTheDocument();
  await userEvent.click(within(screen.getByRole("menu")).getByRole("link", { name: "Home" }));
  expect(await screen.findByRole("heading", { name: "Welcome" })).toBeInTheDocument();
  await userEvent.click(within(screen.getByRole("menu")).getByRole("link", { name: "Items" }));
  expect(await screen.findByRole("heading", { name: "Items" })).toBeInTheDocument();
}, 15_000); // three navigations; the default 5s is tight on a slow CI runner

test("local mode is announced on screen and offers no sign-out", async () => {
  api();
  renderApp("/");
  expect(await screen.findByText("Running without authentication (local mode).")).toBeInTheDocument();
  expect(screen.getByText("Local Dev")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
});

test("home lists exactly the models the API configuration returned, marking the default", async () => {
  api({ "/api/v1/configuration": () => json(200, { allowedModelIds: ["only-this", "and-that"], defaultModelId: "and-that" }) });
  renderApp("/");
  const list = await screen.findByRole("list");
  expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["only-this", "and-thatdefault"]);
});

test("an unknown route shows not found with a way back home", async () => {
  api();
  renderApp("/nope");
  expect(await screen.findByText("Page not found")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Back to home" })).toHaveAttribute("href", "/");
});

test("the theme switch changes the mode without a reload and remembers it", async () => {
  api();
  renderApp("/");
  await userEvent.click(await screen.findByRole("switch", { name: "Dark mode" }));
  expect(screen.getByRole("switch", { name: "Dark mode" })).toBeChecked();
  expect(localStorage.getItem("theme-mode")).toBe("dark");
});

test("without the backend bypass, local mode explains it instead of redirecting", async () => {
  api({ "/auth/me": () => json(401, { error: { code: "auth_invalid_token", message: "Sign in again.", retryable: false } }) });
  renderApp("/");
  expect(await screen.findByText(/LOCAL_AUTH_BYPASS=true/)).toBeInTheDocument();
});

test("with the API down the app says the service is unavailable instead of loading forever", async () => {
  fetchMock.mockResolvedValue(new Response("", { status: 503 }));
  renderApp("/");
  expect(await screen.findByText("The service is not available right now. Try again in a moment.")).toBeInTheDocument();
});
