import { ConfigProvider, theme } from "antd";
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { darkTheme, lightTheme } from "../tokens";

export type ThemeMode = "light" | "dark";

const STORAGE_KEY = "theme-mode";
const DARK_QUERY = "(prefers-color-scheme: dark)";

interface ThemeModeValue {
  mode: ThemeMode;
  setMode(mode: ThemeMode): void;
}

const ThemeModeContext = createContext<ThemeModeValue | undefined>(undefined);

function readChoice(): ThemeMode | null {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === "light" || stored === "dark" ? stored : null;
}

/** Paints the page itself (antd themes components, not the body) from the active tokens. */
function DocumentSurface({ mode }: { mode: ThemeMode }) {
  const { token } = theme.useToken();
  useEffect(() => {
    const { style } = document.body;
    style.backgroundColor = token.colorBgBase;
    style.color = token.colorText;
    style.colorScheme = mode;
  }, [token.colorBgBase, token.colorText, mode]);
  return null;
}

export function ThemeModeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoice] = useState<ThemeMode | null>(readChoice);
  const [systemDark, setSystemDark] = useState(() => window.matchMedia(DARK_QUERY).matches);

  useEffect(() => {
    const query = window.matchMedia(DARK_QUERY);
    const onChange = (event: { matches: boolean }) => setSystemDark(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  const mode: ThemeMode = choice ?? (systemDark ? "dark" : "light");
  const value = useMemo<ThemeModeValue>(
    () => ({
      mode,
      setMode(next) {
        localStorage.setItem(STORAGE_KEY, next);
        setChoice(next);
      },
    }),
    [mode],
  );

  return (
    <ThemeModeContext.Provider value={value}>
      <ConfigProvider theme={mode === "dark" ? darkTheme : lightTheme}>
        <DocumentSurface mode={mode} />
        {children}
      </ConfigProvider>
    </ThemeModeContext.Provider>
  );
}

export function useThemeMode(): ThemeModeValue {
  const value = useContext(ThemeModeContext);
  if (!value) throw new Error("useThemeMode must be used within ThemeModeProvider");
  return value;
}
