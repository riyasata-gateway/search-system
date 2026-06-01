import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useLiveStream } from "../hooks/useLiveStream";
import {
  LayoutDashboard, FlaskConical, Bell, ShieldAlert,
  Settings, Users, LogOut, Activity, Search, Globe2, ChevronDown, Sparkles, Radio, BarChart3,
} from "lucide-react";
import clsx from "clsx";
import { LOCALES, useI18n, type Locale } from "../i18n";

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
  { to: "/lab",            label: "Lab / Brand",     icon: FlaskConical,    roles: LAB_ROLES },
  { to: "/brand-potential", label: "Brand Potential", icon: Sparkles,        roles: LAB_ROLES },
  { to: "/search",         label: "Search",          icon: Search,          roles: ALL_ROLES },
  { to: "/analytics",      label: "Analytics",       icon: BarChart3,       roles: ALL_ROLES },
  { to: "/setup",          label: "Brand Setup",     icon: Settings,        roles: LAB_ROLES },
  { to: "/alerts",         label: "Alerts",          icon: Bell,            roles: ALL_ROLES },
  { to: "/adverse-events", label: "Adverse Events",  icon: ShieldAlert,     roles: ALL_ROLES },
  { to: "/admin",          label: "Admin",           icon: Users,           roles: ["admin"] },
];

const ROLE_STYLE: Record<string, string> = {
  pharmacist:    "bg-emerald-500/10 text-emerald-300 ring-emerald-400/30",
  marketing:     "bg-amber-500/10 text-amber-300 ring-amber-400/30",
  brand_manager: "bg-brand-500/15 text-brand-300 ring-brand-400/30",
  admin:         "bg-accent-500/15 text-accent-300 ring-accent-400/30",
};

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { locale, setLocale, t } = useI18n();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const roleClass = ROLE_STYLE[user?.role ?? ""] ?? ROLE_STYLE.admin;
  const roleLabel = user?.role?.replace("_", " ") ?? "";

  return (
    <div className="flex h-screen bg-[#0b0f1a]">
      <aside className="w-64 relative flex flex-col text-slate-300 border-r border-white/10
                        bg-gradient-to-b from-[#121a2e] via-[#0e1424] to-[#0b0f1a]
                        shadow-[4px_0_40px_-12px_rgba(0,0,0,0.7)]">
        {/* top accent glow */}
        <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-brand-500/10 to-transparent" />
        {/* Brand block */}
        <div className="relative px-5 py-5 border-b border-white/10">
          <div className="flex items-center gap-3">
            <div className="relative shrink-0">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-brand-500 to-accent-500 flex items-center justify-center shadow-glow-accent ring-1 ring-white/10">
                <Activity size={18} className="text-white" strokeWidth={2.5} />
              </div>
              <span className="absolute -right-0.5 -bottom-0.5 w-2.5 h-2.5 bg-emerald-400 rounded-full ring-2 ring-[#0e1424] animate-pulse" />
            </div>
            <div className="min-w-0">
              <p className="font-semibold text-white leading-tight tracking-tight">TDAH</p>
              <p className="text-[10px] uppercase tracking-wider text-slate-500 leading-tight mt-0.5">Trend Data Aggregator Hyperintelligent</p>
            </div>
          </div>
          {user?.role && (
            <span className={clsx("inline-flex items-center gap-1.5 mt-3 px-2 py-0.5 rounded-full text-[11px] font-medium ring-1 capitalize", roleClass)}>
              <span className="w-1.5 h-1.5 rounded-full bg-current opacity-60" />
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
                    isActive
                      ? "text-white bg-white/[0.07] ring-1 ring-white/10 shadow-[0_0_24px_-8px_rgba(91,134,255,0.6)]"
                      : "text-slate-400 hover:bg-white/[0.05] hover:text-white"
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive && (
                      <span className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r-full bg-gradient-to-b from-brand-400 to-accent-400 shadow-[0_0_10px_rgba(91,134,255,0.7)]" />
                    )}
                    <Icon
                      size={17}
                      className={clsx("shrink-0 transition-colors", isActive ? "text-brand-300" : "text-slate-500 group-hover:text-slate-200")}
                    />
                    {label}
                  </>
                )}
              </NavLink>
            ))}
        </nav>

        {/* Footer: language + logout */}
        <div className="relative px-3 pb-4 border-t border-white/10 pt-3 space-y-1">
          <div className="relative">
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-slate-400 hover:bg-white/[0.05] transition-colors">
              <Globe2 size={16} className="text-slate-500 shrink-0" />
              <span className="text-xs text-slate-500">{t("nav.language")}</span>
              <select
                value={locale}
                onChange={(e) => setLocale(e.target.value as Locale)}
                className="ml-auto bg-transparent text-sm font-medium text-slate-200 focus:outline-none cursor-pointer appearance-none pr-5 [&>option]:text-slate-800"
                aria-label={t("nav.language")}
              >
                {LOCALES.map((l) => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))}
              </select>
              <ChevronDown size={13} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-red-500/10 hover:text-red-300 w-full transition-colors"
          >
            <LogOut size={17} className="text-slate-500" />
            {t("nav.logout")}
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-auto surface-app">
        <div className="p-6 lg:p-8 max-w-[1400px] mx-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
