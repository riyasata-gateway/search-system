import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

/**
 * Light / dark theme.
 *
 * The app was authored in native light Tailwind utilities and reskinned to dark
 * via the `.surface-app` layer in index.css. So the theme switch is structural,
 * not a thousand class edits: in DARK mode the workspace carries `.surface-app`
 * (dark reskin applies); in LIGHT mode it carries `.surface-light` and the pages
 * render in their native light utilities. The chosen theme is also reflected as
 * `data-theme` on <html> so global chrome (body, scrollbar, focus ring, glass)
 * can flip via CSS. Per-role accent (`--role-accent`) is theme-independent.
 *
 * Ships dark by default (the product's "command center" identity); the choice is
 * remembered per browser.
 */
export type Theme = "light" | "dark";

const STORAGE_KEY = "tdah-theme";

interface ThemeContextValue {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function initialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const saved = window.localStorage.getItem(STORAGE_KEY);
  return saved === "light" || saved === "dark" ? saved : "dark";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    window.localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const value: ThemeContextValue = {
    theme,
    setTheme: setThemeState,
    toggleTheme: () => setThemeState((p) => (p === "dark" ? "light" : "dark")),
  };

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}