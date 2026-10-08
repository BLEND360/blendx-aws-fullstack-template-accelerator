import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { itemsFetch } from "../../test/standin";
import { ItemsPage } from "./ItemsPage";

const unrouted = () => new Response("", { status: 404 });

function mount(fetchImpl = itemsFetch(unrouted)) {
  vi.stubGlobal("fetch", fetchImpl);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ItemsPage />
    </QueryClientProvider>,
  );
  return fetchImpl;
}

const nameBox = () => screen.getByRole("textbox", { name: "Name" });
const submit = () => userEvent.click(screen.getByRole("button", { name: "Add item" }));

test("shows a loader while the list loads, then the empty state", async () => {
  mount();
  expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
  expect(await screen.findByText("No items yet. Create your first one.")).toBeInTheDocument();
});

test("lists the user's items", async () => {
  mount(
    itemsFetch(unrouted, [
      { id: "item-1", name: "First", description: "about first", createdAt: "2026-10-05T00:00:00Z" },
    ]),
  );
  expect(await screen.findByText("First")).toBeInTheDocument();
  expect(screen.getByText("about first")).toBeInTheDocument();
  expect(screen.queryByText(/No items yet/)).not.toBeInTheDocument();
});

test("a created item appears in the list without reloading, and the form clears", async () => {
  const fetchImpl = mount();
  await screen.findByText(/No items yet/);
  await userEvent.type(nameBox(), "Brand new");
  await submit();
  expect(await screen.findByText("Brand new")).toBeInTheDocument();
  expect(screen.queryByText(/No items yet/)).not.toBeInTheDocument();
  expect(nameBox()).toHaveValue("");
  expect(fetchImpl.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});

test("a rejected field is explained next to the field and what was typed is kept", async () => {
  mount();
  await screen.findByText(/No items yet/);
  await userEvent.type(screen.getByRole("textbox", { name: "Description" }), "keep me");
  await submit(); // empty name: the API says so
  expect(await screen.findByText("Name is required.")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Description" })).toHaveValue("keep me");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("editing a field clears its error", async () => {
  mount();
  await screen.findByText(/No items yet/);
  await submit();
  await screen.findByText("Name is required.");
  await userEvent.type(nameBox(), "x");
  await waitFor(() => expect(screen.queryByText("Name is required.")).not.toBeInTheDocument());
});

test("another failure shows the error with its request id and a retry that works", async () => {
  const fetchImpl = mount();
  await screen.findByText(/No items yet/);
  await userEvent.type(nameBox(), "error");
  await submit();
  expect(await screen.findByText("The data store is temporarily unavailable.")).toBeInTheDocument();
  expect(screen.getByText(/Request ID: standin-/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  expect(nameBox()).toHaveValue("error");
  expect(fetchImpl.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(fetchImpl.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(2));
});

test("a failed load shows the error with retry", async () => {
  const failing = vi.fn<typeof fetch>().mockResolvedValue(
    new Response(JSON.stringify({ error: { code: "data_throttled", message: "The data store is busy.", retryable: true } }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    }),
  );
  mount(failing);
  expect(await screen.findByText("The data store is busy.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});
