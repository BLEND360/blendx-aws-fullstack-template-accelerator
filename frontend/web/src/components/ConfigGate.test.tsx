import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { ConfigGate, useClientConfig } from "./ConfigGate";

const fetchMock = vi.fn<typeof fetch>();
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function Page() {
  const config = useClientConfig();
  return <p>{`default=${config.defaultModelId}; all=${config.allowedModelIds.join(",")}`}</p>;
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Routes>
          <Route element={<ConfigGate />}>
            <Route index element={<Page />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

test("shows a loader, then renders the page with the configuration the API returned", async () => {
  fetchMock.mockResolvedValue(json(200, { allowedModelIds: ["m1", "m2"], defaultModelId: "m1" }));
  mount();
  expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
  expect(await screen.findByText("default=m1; all=m1,m2")).toBeInTheDocument();
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/configuration");
});

test("a failure shows the error with retry and renders no page; retry recovers", async () => {
  fetchMock
    .mockResolvedValueOnce(json(500, { error: { code: "internal_error", message: "Boom.", retryable: false, requestId: "rid-c" } }))
    .mockResolvedValueOnce(json(200, { allowedModelIds: ["m1"], defaultModelId: "m1" }));
  mount();
  expect(await screen.findByText("Boom.")).toBeInTheDocument();
  expect(screen.getByText("Request ID: rid-c")).toBeInTheDocument();
  expect(screen.queryByText(/default=/)).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("default=m1; all=m1")).toBeInTheDocument();
});
