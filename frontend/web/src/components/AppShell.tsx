import { Alert, Button, Flex, Layout, Menu, Space, Switch, Typography, theme } from "antd";
import { Link, Outlet, useLocation } from "react-router";
import { useAuth } from "../auth/useAuth";
import { messages } from "../messages";
import { useThemeMode } from "../theme/ThemeModeProvider";
import { BrandLogo } from "../tokens";

// Adding a page to the app = a route in App.tsx plus a row here.
const NAV = [
  { path: "/", label: messages.navHome },
  { path: "/chat", label: messages.navChat },
  { path: "/items", label: messages.navItems },
];

export function AppShell() {
  const { state, signOut } = useAuth();
  const { mode, setMode } = useThemeMode();
  const { token } = theme.useToken();
  const { pathname } = useLocation();
  const user = state.status === "authenticated" || state.status === "local" ? state.user : null;

  return (
    <Layout style={{ minHeight: "100vh" }}>
      {state.status === "local" && <Alert banner type="warning" title={messages.localMode} />}
      <Layout.Header style={{ background: token.colorBgContainer, paddingInline: 24 }}>
        <Flex align="center" gap="large" style={{ height: "100%" }}>
          <BrandLogo height={32} mode={mode} />
          <Menu
            mode="horizontal"
            selectedKeys={[pathname]}
            style={{ flex: 1, minWidth: 0, borderBottom: "none" }}
            items={NAV.map(({ path, label }) => ({ key: path, label: <Link to={path}>{label}</Link> }))}
          />
          <Space size="middle">
            <Switch
              checked={mode === "dark"}
              onChange={(checked) => setMode(checked ? "dark" : "light")}
              checkedChildren="🌙"
              unCheckedChildren="☀"
              aria-label={messages.darkMode}
            />
            {user && <Typography.Text>{user.name}</Typography.Text>}
            {state.status === "authenticated" && <Button onClick={signOut}>{messages.signOut}</Button>}
          </Space>
        </Flex>
      </Layout.Header>
      <Layout.Content style={{ padding: 24 }}>
        <Outlet />
      </Layout.Content>
    </Layout>
  );
}
