import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "../api/client";
import { ApiErrorAlert } from "./ApiErrorAlert";

const make = (retryable: boolean, requestId: string | null = "rid-9") =>
  new ApiError({ status: 503, code: "data_throttled", message: "The data store is busy.", retryable, requestId });

test("shows the error's message and request id", () => {
  render(<ApiErrorAlert error={make(false)} />);
  expect(screen.getByText("The data store is busy.")).toBeInTheDocument();
  expect(screen.getByText("Request ID: rid-9")).toBeInTheDocument();
});

test("omits the request id when there is none", () => {
  render(<ApiErrorAlert error={make(false, null)} />);
  expect(screen.queryByText(/Request ID/)).not.toBeInTheDocument();
});

test("a retryable error offers retry", async () => {
  const onRetry = vi.fn();
  render(<ApiErrorAlert error={make(true)} onRetry={onRetry} />);
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(onRetry).toHaveBeenCalledOnce();
});

test("a non-retryable error offers no retry", () => {
  render(<ApiErrorAlert error={make(false)} onRetry={() => {}} />);
  expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
});

test("forceRetry offers retry on a non-retryable error", () => {
  render(<ApiErrorAlert error={make(false)} onRetry={() => {}} forceRetry />);
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});
