import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeModeProvider, useThemeMode } from "./ThemeModeProvider";

type Listener = (event: { matches: boolean }) => void;

function mockSystemPreference(dark: boolean) {
  const listeners = new Set<Listener>();
  let matches = dark;
  window.matchMedia = ((query: string) => ({
    get matches() {
      return matches;
    },
    media: query,
    addEventListener: (_: string, l: Listener) => listeners.add(l),
    removeEventListener: (_: string, l: Listener) => listeners.delete(l),
  })) as unknown as typeof window.matchMedia;
  return (next: boolean) => {
    matches = next;
    listeners.forEach((l) => l({ matches: next }));
  };
}

function Probe() {
  const { mode, setMode } = useThemeMode();
  return (
    <>
      <span data-testid="mode">{mode}</span>
      <button onClick={() => setMode("dark")}>dark</button>
      <button onClick={() => setMode("light")}>light</button>
    </>
  );
}

const renderProbe = () =>
  render(
    <ThemeModeProvider>
      <Probe />
    </ThemeModeProvider>,
  );

test("without a choice the mode follows the operating system", () => {
  mockSystemPreference(true);
  renderProbe();
  expect(screen.getByTestId("mode")).toHaveTextContent("dark");
});

test("a system change is followed while the user has not chosen", () => {
  const setSystemDark = mockSystemPreference(false);
  renderProbe();
  act(() => setSystemDark(true));
  expect(screen.getByTestId("mode")).toHaveTextContent("dark");
});

test("choosing a mode applies it without reloading and remembers it", async () => {
  mockSystemPreference(false);
  renderProbe();
  await userEvent.click(screen.getByText("dark"));
  expect(screen.getByTestId("mode")).toHaveTextContent("dark");
  expect(localStorage.getItem("theme-mode")).toBe("dark");
  expect(document.body.style.colorScheme).toBe("dark");
});

test("a remembered choice beats the operating system", () => {
  mockSystemPreference(true);
  localStorage.setItem("theme-mode", "light");
  renderProbe();
  expect(screen.getByTestId("mode")).toHaveTextContent("light");
});

test("an invalid stored value is ignored", () => {
  mockSystemPreference(true);
  localStorage.setItem("theme-mode", "sepia");
  renderProbe();
  expect(screen.getByTestId("mode")).toHaveTextContent("dark");
});

test("the document surface comes from the active theme, not from literals", () => {
  mockSystemPreference(false);
  renderProbe();
  expect(document.body.style.backgroundColor).not.toBe("");
});

test("unavailable storage does not break the provider; the choice still applies", async () => {
  mockSystemPreference(false);
  const blocked = () => {
    throw new Error("blocked");
  };
  const spies = [vi.spyOn(localStorage, "getItem").mockImplementation(blocked), vi.spyOn(localStorage, "setItem").mockImplementation(blocked)];
  renderProbe();
  expect(screen.getByTestId("mode")).toHaveTextContent("light");
  await userEvent.click(screen.getByText("dark"));
  expect(screen.getByTestId("mode")).toHaveTextContent("dark");
  spies.forEach((spy) => spy.mockRestore());
});
