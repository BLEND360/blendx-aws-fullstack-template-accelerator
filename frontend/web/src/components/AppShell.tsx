import { ExclamationCircleOutlined, MoonOutlined, SunOutlined } from "@ant-design/icons";
import { Button, Layout, Menu, Switch } from "antd";
import { Link, Outlet, useLocation } from "react-router";
import { useAuth } from "../auth/useAuth";
import { messages } from "../messages";
import { useThemeMode } from "../theme/ThemeModeProvider";
import { BrandLogo } from "../tokens";
import "../ui/design.css";

// Adding a page to the app = a route in App.tsx plus a row here.
const NAV = [
  { path: "/", label: messages.navHome },
  { path: "/chat", label: messages.navChat },
  { path: "/items", label: messages.navItems },
];

export function AppShell() {
  const { state, signOut } = useAuth();
  const { mode, setMode } = useThemeMode();
  const { pathname } = useLocation();
  const user = state.status === "authenticated" || state.status === "local" ? state.user : null;

  return (
    <Layout className="app-shell">
      {state.status === "local" && (
        <div className="dev-banner" role="status">
          <ExclamationCircleOutlined aria-hidden />
          {messages.localMode}
        </div>
      )}
      <Layout.Header className="app-header">
        <div className="app-header-inner">
          <BrandLogo height={30} mode={mode} />
          <Menu
            className="app-nav"
            mode="horizontal"
            selectedKeys={[pathname]}
            items={NAV.map(({ path, label }) => ({ key: path, label: <Link to={path}>{label}</Link> }))}
          />
          <div className="app-user">
            <Switch
              size="small"
              checked={mode === "dark"}
              onChange={(checked) => setMode(checked ? "dark" : "light")}
              checkedChildren={<MoonOutlined />}
              unCheckedChildren={<SunOutlined />}
              aria-label={messages.darkMode}
            />
            {user && (
              <span className="app-user-name">
                <span className="app-user-avatar" aria-hidden>
                  {user.name.slice(0, 1).toUpperCase()}
                </span>
                <span>{user.name}</span>
              </span>
            )}
            {state.status === "authenticated" && <Button onClick={signOut}>{messages.signOut}</Button>}
          </div>
        </div>
      </Layout.Header>
      <Layout.Content className="app-content">
        <Outlet />
      </Layout.Content>
    </Layout>
  );
}
