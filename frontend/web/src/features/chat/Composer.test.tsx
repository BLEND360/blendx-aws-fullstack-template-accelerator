import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeModeProvider } from "../../theme/ThemeModeProvider";
import { MAX_MESSAGE_CHARS } from "./chatState";
import { Composer } from "./Composer";

function show(props: Partial<{ disabled: boolean; onSend: (t: string) => void }> = {}) {
  const onSend = props.onSend ?? vi.fn();
  const view = render(
    <ThemeModeProvider>
      <Composer disabled={props.disabled ?? false} onSend={onSend} />
    </ThemeModeProvider>,
  );
  const rerender = (disabled: boolean) =>
    view.rerender(
      <ThemeModeProvider>
        <Composer disabled={disabled} onSend={onSend} />
      </ThemeModeProvider>,
    );
  return { onSend, rerender };
}
const field = () => screen.getByRole("textbox", { name: "Message" });
const sendButton = () => screen.getByRole("button", { name: "Send" });

test("the field and the action have accessible names", () => {
  show();
  expect(field()).toBeInTheDocument();
  expect(sendButton()).toBeInTheDocument();
});

test("sending is off for an empty message and for one that is only whitespace", async () => {
  show();
  expect(sendButton()).toBeDisabled();
  await userEvent.type(field(), "   ");
  expect(sendButton()).toBeDisabled();
  await userEvent.type(field(), "a");
  expect(sendButton()).toBeEnabled();
});

test("clicking send hands over the text and empties the field", async () => {
  const { onSend } = show();
  await userEvent.type(field(), "hello there");
  await userEvent.click(sendButton());
  expect(onSend).toHaveBeenCalledWith("hello there");
  expect(field()).toHaveValue("");
});

test("Enter sends and Shift+Enter makes a new line", async () => {
  const { onSend } = show();
  await userEvent.type(field(), "line one{Shift>}{Enter}{/Shift}line two");
  expect(onSend).not.toHaveBeenCalled();
  expect(field()).toHaveValue("line one\nline two");
  await userEvent.type(field(), "{Enter}");
  expect(onSend).toHaveBeenCalledWith("line one\nline two");
});

test("Enter on an empty field sends nothing", async () => {
  const { onSend } = show();
  await userEvent.type(field(), "{Enter}");
  expect(onSend).not.toHaveBeenCalled();
});

test("a key pressed while composing text with an IME is not a send", () => {
  const { onSend } = show();
  fireEvent.change(field(), { target: { value: "にほん" } });
  fireEvent.keyDown(field(), { key: "Enter", code: "Enter", keyCode: 229, isComposing: true });
  expect(onSend).not.toHaveBeenCalled();
});

test("while a turn runs the action is off and Enter does nothing, but typing still works", async () => {
  const { onSend } = show({ disabled: true });
  await userEvent.type(field(), "next question{Enter}");
  expect(field()).toHaveValue("next question");
  expect(sendButton()).toBeDisabled();
  expect(onSend).not.toHaveBeenCalled();
});

test("a message over the limit says so and cannot be sent, one at the limit can", () => {
  const { onSend } = show();
  fireEvent.change(field(), { target: { value: "x".repeat(MAX_MESSAGE_CHARS + 1) } });
  expect(screen.getByRole("alert")).toHaveTextContent("This message is too long to send.");
  expect(field()).toHaveAttribute("aria-invalid", "true");
  expect(sendButton()).toBeDisabled();
  fireEvent.keyDown(field(), { key: "Enter", code: "Enter", keyCode: 13 });
  expect(onSend).not.toHaveBeenCalled();

  fireEvent.change(field(), { target: { value: "x".repeat(MAX_MESSAGE_CHARS) } });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(sendButton()).toBeEnabled();
});

test("a counter shows near the limit and not before", () => {
  show();
  fireEvent.change(field(), { target: { value: "x".repeat(100) } });
  expect(screen.queryByText(/\/ 12000/)).not.toBeInTheDocument();
  fireEvent.change(field(), { target: { value: "x".repeat(Math.floor(MAX_MESSAGE_CHARS * 0.8)) } });
  expect(screen.getByText(/\/ 12000/)).toBeInTheDocument();
});

test("the cursor is in the field when it becomes ready, and comes back when a turn ends", () => {
  const { rerender } = show({ disabled: true });
  expect(field()).not.toHaveFocus();
  rerender(false); // the conversation finished loading
  expect(field()).toHaveFocus();

  screen.getByRole("button", { name: "Send" }).focus(); // the user moved on during the turn
  rerender(true);
  rerender(false); // the turn ended
  expect(field()).toHaveFocus();
});

test("it can be used with the keyboard alone", async () => {
  const { onSend } = show();
  expect(field()).toHaveFocus(); // the cursor starts in the field: no click needed
  await userEvent.keyboard("hi");
  await userEvent.tab();
  expect(sendButton()).toHaveFocus();
  await userEvent.keyboard("{Enter}");
  expect(onSend).toHaveBeenCalledWith("hi");
});
