import { useQuery } from "@tanstack/react-query";
import { createContext, useContext } from "react";
import { Outlet } from "react-router";
import { fetchConfiguration } from "../api/configuration";
import type { ClientConfiguration } from "../api/configuration";
import { asApiError } from "../api/client";
import { ApiErrorAlert } from "../ui/ApiErrorAlert";
import { LoadingIndicator } from "../ui/LoadingIndicator";

const ConfigContext = createContext<ClientConfiguration | undefined>(undefined);

/** Loads the client configuration once there is a session and renders the routes
 * below only when it is available: no defaults of our own to fall back on. */
export function ConfigGate() {
  const query = useQuery({
    queryKey: ["configuration"],
    queryFn: ({ signal }) => fetchConfiguration(signal),
    retry: false,
  });

  if (query.isPending) return <LoadingIndicator />;
  if (query.isError) {
    return (
      <div style={{ padding: 24 }}>
        <ApiErrorAlert error={asApiError(query.error)} onRetry={() => void query.refetch()} forceRetry />
      </div>
    );
  }
  return (
    <ConfigContext.Provider value={query.data}>
      <Outlet />
    </ConfigContext.Provider>
  );
}

export function useClientConfig(): ClientConfiguration {
  const value = useContext(ConfigContext);
  if (!value) throw new Error("useClientConfig must be used below ConfigGate");
  return value;
}
