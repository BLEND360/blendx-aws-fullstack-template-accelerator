import { Route, Routes } from "react-router";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { AppShell } from "./components/AppShell";
import { ConfigGate } from "./components/ConfigGate";
import { ItemsPage } from "./features/items/ItemsPage";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";
import { NotFound } from "./pages/NotFound";

/** Routes only; the providers (theme, query, router, auth) wrap it in main.tsx. */
export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<ConfigGate />}>
          <Route element={<AppShell />}>
            <Route index element={<Home />} />
            <Route path="items" element={<ItemsPage />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
