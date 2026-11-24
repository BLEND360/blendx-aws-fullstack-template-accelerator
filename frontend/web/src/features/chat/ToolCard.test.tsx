import { render, screen, within } from "@testing-library/react";
import { ThemeModeProvider } from "../../theme/ThemeModeProvider";
import type { ToolItem } from "./chatState";
import { ToolCard } from "./ToolCard";

const show = (item: ToolItem) => render(<ThemeModeProvider><ToolCard item={item} /></ThemeModeProvider>);
const card = () => screen.getByRole("group");

test("a tool that is still running shows its label and a running state, and no result yet", () => {
  show({ kind: "tool", callId: "t1", label: "Checking the time", status: "running" });
  expect(within(card()).getByText("Checking the time")).toBeInTheDocument();
  expect(within(card()).getByText("Running")).toBeInTheDocument();
  expect(screen.queryByText("Input")).not.toBeInTheDocument();
  expect(screen.queryByText("Result")).not.toBeInTheDocument();
});

test("the input appears as soon as it is known, before the result", () => {
  show({ kind: "tool", callId: "t1", label: "Checking the time", status: "running", input: { format: "iso" } });
  expect(screen.getByText("Input")).toBeInTheDocument();
  expect(card()).toHaveTextContent('"format": "iso"');
  expect(screen.queryByText("Result")).not.toBeInTheDocument();
});

test("a finished tool says done and shows its input and its result", () => {
  show({ kind: "tool", callId: "t1", label: "Checking the time", status: "success", input: { format: "iso" }, result: { time: "2026-10-09T16:00:00+00:00" } });
  expect(within(card()).getByText("Done")).toBeInTheDocument();
  expect(card()).toHaveTextContent('"time": "2026-10-09T16:00:00+00:00"');
});

test("a failure is told in words, not only by color", () => {
  show({ kind: "tool", callId: "t1", label: "Lookup", status: "error", result: { code: "tool_failed" } });
  expect(within(card()).getByText("Failed")).toBeInTheDocument();
  expect(card()).toHaveAccessibleName("Lookup: Failed");
});

test("every state has its own accessible name", () => {
  const names = (["running", "success", "error"] as const).map((status) => {
    const { unmount } = show({ kind: "tool", callId: "t", label: "X", status });
    const name = card().getAttribute("aria-label");
    unmount();
    return name;
  });
  expect(names).toEqual(["X: Running", "X: Done", "X: Failed"]);
});

test("it shows the label, input, status and result and nothing else it was handed", () => {
  const item = { kind: "tool", callId: "internal-id-123", label: "X", status: "success", input: {}, result: {}, secret: "do-not-show" } as ToolItem;
  show(item);
  expect(card()).not.toHaveTextContent("do-not-show");
  expect(card()).not.toHaveTextContent("internal-id-123");
});

test("content is shown as text, never interpreted as markup", () => {
  show({ kind: "tool", callId: "t", label: "X", status: "success", result: { html: "<img src=x onerror=alert(1)>" } });
  expect(card().querySelector("img")).toBeNull();
  expect(card()).toHaveTextContent("<img src=x onerror=alert(1)>");
});
