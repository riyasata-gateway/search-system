import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useLiveStream } from "../hooks/useLiveStream";
import {
  LayoutDashboard, Bell, ShieldAlert,
  Settings, Users, LogOut, Activity, Search, Globe2, ChevronDown, Sparkles, Radio, BarChart3,
  Sun, Moon,
} from "lucide-react";
import clsx from "clsx";
import { LOCALES, useI18n, type Locale } from "../i18n";
import { themeFor, roleCssVars } from "../lib/roleTheme";
import { useTheme } from "../lib/theme";

const LIVE_STATUS_STYLE: Record<string, string> = {
  open: "bg-emerald-500/10 text-emerald-300 border-emerald-400/30",
  connecting: "bg-amber-500/10 text-amber-300 border-amber-400/30",
  error: "bg-red-500/10 text-red-300 border-red-400/30",
  closed: "bg-white/5 text-slate-400 border-white/10",
};

const LIVE_STATUS_LABEL: Record<string, string> = {
  open: "Live",
  connecting: "Connecting…",
  error: "Reconnecting",
  closed: "Offline",
};

function LiveStatusPill() {
  // Subscribe to the cheap signals channel — heartbeat keeps the connection
  // open even when no data flows, which is exactly what we want for the pill.
  const { status, lastEvent } = useLiveStream<{ event?: string }>("signals");
  const className = LIVE_STATUS_STYLE[status] ?? LIVE_STATUS_STYLE.closed;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 mt-2 px-2 py-0.5 rounded-full text-[10px] font-semibold border",
        className
      )}
      title={lastEvent?.event ? `Last event: ${lastEvent.event}` : "Real-time stream"}
    >
      <Radio size={9} className={status === "open" ? "animate-pulse" : ""} />
      {LIVE_STATUS_LABEL[status]}
    </span>
  );
}

const LAB_ROLES = ["marketing", "brand_manager", "admin"];
const ALL_ROLES = ["pharmacist", "marketing", "brand_manager", "admin"];

const navItems = [
  { to: "/pharmacist",     label: "Pharmacist",      icon: LayoutDashboard, roles: ["pharmacist", "admin"] },
  { to: "/brand-pulse",    label: "Brand Pulse",     icon: Activity,        roles: LAB_ROLES },
  { to: "/brand-potential", label: "Brand Potential", icon: Sparkles,        roles: LAB_ROLES },
  { to: "/search",         label: "Search",          icon: Search,          roles: ALL_ROLES },
  { to: "/analytics",      label: "Analytics",       icon: BarChart3,       roles: ALL_ROLES },
  { to: "/setup",          label: "Brand Setup",     icon: Settings,        roles: LAB_ROLES },
  { to: "/alerts",         label: "Alerts",          icon: Bell,            roles: ALL_ROLES },
  { to: "/adverse-events", label: "Adverse Events",  icon: ShieldAlert,     roles: ["pharmacist", "admin"] },
  { to: "/admin",          label: "Admin",           icon: Users,           roles: ["admin"] },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { locale, setLocale, t } = useI18n();
  const { theme: mode, toggleTheme } = useTheme();
  const dark = mode === "dark";

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const roleLabel = user?.role?.replace("_", " ") ?? "";
  const theme = themeFor(user?.role);
  const LogoIcon = theme.Icon;

  // Theme-aware sidebar chrome. The content area handles itself: dark mode adds
  // `.surface-app` (the dark page reskin); light mode uses `.surface-light` and
  // pages render in their native light Tailwind utilities.
  const ui = dark
    ? {
        shellBg: "bg-[#0b0f1a]",
        aside: "text-slate-300 border-white/10 bg-gradient-to-b from-[#121a2e] via-[#0e1424] to-[#0b0f1a] shadow-[4px_0_40px_-12px_rgba(0,0,0,0.7)]",
        divider: "border-white/10",
        brandName: "text-white",
        subtitle: "text-slate-500",
        navActive: "text-white bg-white/[0.07] ring-1 ring-white/10",
        navIdle: "text-slate-400 hover:bg-white/[0.05] hover:text-white",
        navIconIdle: "text-slate-500 group-hover:text-slate-200",
        footText: "text-slate-400",
        footHover: "hover:bg-white/[0.05]",
        footIcon: "text-slate-500",
        langText: "text-slate-200",
        langMuted: "text-slate-500",
        logoDotRing: "ring-[#0e1424]",
        canvas: "surface-app",
      }
    : {
        shellBg: "bg-[#eef2f8]",
        aside: "text-slate-600 border-slate-200 bg-gradient-to-b from-white to-slate-50 shadow-[4px_0_40px_-20px_rgba(15,23,42,0.18)]",
        divider: "border-slate-200",
        brandName: "text-slate-900",
        subtitle: "text-slate-400",
        navActive: "text-slate-900 bg-slate-100 ring-1 ring-slate-200",
        navIdle: "text-slate-500 hover:bg-slate-100 hover:text-slate-900",
        navIconIdle: "text-slate-400 group-hover:text-slate-600",
        footText: "text-slate-500",
        footHover: "hover:bg-slate-100",
        footIcon: "text-slate-400",
        langText: "text-slate-700",
        langMuted: "text-slate-400",
        logoDotRing: "ring-white",
        canvas: "surface-light",
      };

  return (
    <div className={clsx("flex h-screen", ui.shellBg)} data-role={user?.role} style={roleCssVars(user?.role)}>
      <aside className={clsx("w-64 relative flex flex-col border-r", ui.aside)}>
        {/* top accent glow — tinted by the active role */}
        <div
          className="pointer-events-none absolute inset-x-0 top-0 h-40"
          style={{ background: `linear-gradient(to bottom, rgba(${theme.accentRgb},${dark ? 0.14 : 0.1}), transparent)` }}
        />
        {/* Brand block — per-role product identity */}
        <div className={clsx("relative px-5 py-5 border-b", ui.divider)}>
          <div className="flex items-center gap-3">
            <div className="relative shrink-0">
              <div
                className="w-9 h-9 rounded-xl flex items-center justify-center ring-1 ring-white/10"
                style={{
                  background: `linear-gradient(135deg, ${theme.gradient[0]}, ${theme.gradient[1]})`,
                  boxShadow: `0 8px 30px -8px rgba(${theme.accentRgb},0.55)`,
                }}
              >
                <LogoIcon size={18} className="text-white" strokeWidth={2.5} />
              </div>
              <span className={clsx("absolute -right-0.5 -bottom-0.5 w-2.5 h-2.5 bg-emerald-400 rounded-full ring-2 animate-pulse", ui.logoDotRing)} />
            </div>
            <div className="min-w-0">
              <p className={clsx("font-semibold leading-tight tracking-tight truncate", ui.brandName)} title={theme.product}>{theme.product}</p>
              <p className={clsx("text-[10px] uppercase tracking-wider leading-tight mt-0.5", ui.subtitle)}>{theme.subtitle}</p>
            </div>
          </div>
          {/* Role badge — the logged-in role, unmistakable: role icon + name in the
              role's own accent. Single source of truth = roleTheme, so it stays
              correct in both light and dark. */}
          {user?.role && (
            <span
              className="inline-flex items-center gap-1.5 mt-3 px-2.5 py-1 rounded-full text-[11px] font-semibold capitalize"
              style={{
                background: `rgba(${theme.accentRgb}, ${dark ? 0.16 : 0.12})`,
                color: dark ? theme.accent : theme.gradient[0],
                boxShadow: `inset 0 0 0 1px rgba(${theme.accentRgb}, ${dark ? 0.4 : 0.5})`,
              }}
              title={`Signed in as ${roleLabel}`}
            >
              <LogoIcon size={12} strokeWidth={2.6} />
              {roleLabel}
            </span>
          )}
          <div>
            <LiveStatusPill />
          </div>
        </div>

        {/* Nav */}
        <nav className="relative flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          {navItems
            .filter((item) => user && item.roles.includes(user.role))
            .map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  clsx(
                    "group relative flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-150",
                    isActive ? ui.navActive : ui.navIdle
                  )
                }
                style={({ isActive }) =>
                  isActive
                    ? { boxShadow: `0 0 24px -8px rgba(${theme.accentRgb},0.6)` }
                    : undefined
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive && (
                      <span
                        className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r-full"
                        style={{
                          background: `linear-gradient(${theme.gradient[0]}, ${theme.gradient[1]})`,
                          boxShadow: `0 0 10px rgba(${theme.accentRgb},0.7)`,
                        }}
                      />
                    )}
                    <Icon
                      size={17}
                      className={clsx("shrink-0 transition-colors", !isActive && ui.navIconIdle)}
                      style={isActive ? { color: theme.accent } : undefined}
                    />
                    {label}
                  </>
                )}
              </NavLink>
            ))}
        </nav>

        {/* Footer: theme toggle + language + logout */}
        <div className={clsx("relative px-3 pb-4 border-t pt-3 space-y-1", ui.divider)}>
          <button
            onClick={toggleTheme}
            className={clsx("flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium w-full transition-colors", ui.footText, ui.footHover)}
            title={dark ? "Switch to light mode" : "Switch to dark mode"}
          >
            {dark ? <Sun size={17} className={ui.footIcon} /> : <Moon size={17} className={ui.footIcon} />}
            {dark ? "Light mode" : "Dark mode"}
          </button>
          <div className="relative">
            <div className={clsx("flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors", ui.footText, ui.footHover)}>
              <Globe2 size={16} className={clsx("shrink-0", ui.footIcon)} />
              <span className={clsx("text-xs", ui.langMuted)}>{t("nav.language")}</span>
              <select
                value={locale}
                onChange={(e) => setLocale(e.target.value as Locale)}
                className={clsx("ml-auto bg-transparent text-sm font-medium focus:outline-none cursor-pointer appearance-none pr-5 [&>option]:text-slate-800", ui.langText)}
                aria-label={t("nav.language")}
              >
                {LOCALES.map((l) => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))}
              </select>
              <ChevronDown size={13} className={clsx("absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none", ui.footIcon)} />
            </div>
          </div>
          <button
            onClick={handleLogout}
            className={clsx("flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium w-full transition-colors hover:bg-red-500/10 hover:text-red-400", ui.footText)}
          >
            <LogOut size={17} className={ui.footIcon} />
            {t("nav.logout")}
          </button>
        </div>
      </aside>

      <main className={clsx("flex-1 overflow-auto", ui.canvas)}>
        {/* Full page breadth — no centred max-width cap. */}
        <div className="p-6 lg:p-8 w-full">
          <Outlet />
        </div>
      </main>
    </div>
  );
}