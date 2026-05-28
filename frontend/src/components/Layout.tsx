import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useLiveStream } from "../hooks/useLiveStream";
import {
  LayoutDashboard, FlaskConical, Bell, ShieldAlert,
  Settings, Users, LogOut, Activity, Search, Globe2, ChevronDown, Sparkles, Radio,
} from "lucide-react";
import clsx from "clsx";
import { LOCALES, useI18n, type Locale } from "../i18n";

const LIVE_STATUS_STYLE: Record<string, string> = {
  open: "bg-emerald-100 text-emerald-700 border-emerald-200",
  connecting: "bg-amber-100 text-amber-700 border-amber-200",
  error: "bg-red-100 text-red-700 border-red-200",
  closed: "bg-slate-100 text-slate-500 border-slate-200",
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

const navItems = [
  { to: "/pharmacist",     label: "Pharmacist",     icon: LayoutDashboard, roles: ["pharmacist", "admin"] },
  { to: "/lab",            label: "Lab / Brand",    icon: FlaskConical,    roles: ["lab_user", "admin"] },
  { to: "/brand-potential", label: "Brand Potential", icon: Sparkles,       roles: ["lab_user", "admin"] },
  { to: "/search",         label: "Search",         icon: Search,          roles: ["pharmacist", "lab_user", "admin"] },
  { to: "/setup",          label: "Brand Setup",    icon: Settings,        roles: ["lab_user", "admin"] },
  { to: "/alerts",         label: "Alerts",         icon: Bell,            roles: ["pharmacist", "lab_user", "admin"] },
  { to: "/adverse-events", label: "Adverse Events", icon: ShieldAlert,     roles: ["pharmacist", "lab_user", "admin"] },
  { to: "/admin",          label: "Admin",          icon: Users,           roles: ["admin"] },
];

const ROLE_STYLE: Record<string, string> = {
  pharmacist: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  lab_user:   "bg-brand-50 text-brand-700 ring-brand-200",
  admin:      "bg-accent-50 text-accent-700 ring-accent-200",
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
    <div className="flex h-screen bg-slate-50">
      <aside className="w-64 bg-white/80 backdrop-blur border-r border-slate-200/70 flex flex-col">
        {/* Brand block */}
        <div className="px-5 py-5 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="relative shrink-0">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-brand-500 to-accent-500 flex items-center justify-center shadow-soft">
                <Activity size={18} className="text-white" strokeWidth={2.5} />
              </div>
              <span className="absolute -right-0.5 -bottom-0.5 w-2.5 h-2.5 bg-emerald-500 rounded-full ring-2 ring-white" />
            </div>
            <div className="min-w-0">
              <p className="font-semibold text-slate-900 leading-tight">TDAH</p>
              <p className="text-[10px] uppercase tracking-wider text-slate-400 leading-tight mt-0.5">Trend Data Aggregator Hyperintelligent</p>
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
        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
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
                      ? "text-brand-700 bg-gradient-to-r from-brand-50 to-transparent"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive && (
                      <span className="absolute left-0 top-2 bottom-2 w-1 rounded-r-full bg-gradient-to-b from-brand-500 to-accent-500" />
                    )}
                    <Icon
                      size={17}
                      className={clsx("shrink-0", isActive ? "text-brand-600" : "text-slate-400 group-hover:text-slate-600")}
                    />
                    {label}
                  </>
                )}
              </NavLink>
            ))}
        </nav>

        {/* Footer: language + logout */}
        <div className="px-3 pb-4 border-t border-slate-100 pt-3 space-y-1">
          <div className="relative">
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors">
              <Globe2 size={16} className="text-slate-400 shrink-0" />
              <span className="text-xs text-slate-400">{t("nav.language")}</span>
              <select
                value={locale}
                onChange={(e) => setLocale(e.target.value as Locale)}
                className="ml-auto bg-transparent text-sm font-medium text-slate-700 focus:outline-none cursor-pointer appearance-none pr-5"
                aria-label={t("nav.language")}
              >
                {LOCALES.map((l) => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))}
              </select>
              <ChevronDown size={13} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-slate-600 hover:bg-red-50 hover:text-red-600 w-full transition-colors"
          >
            <LogOut size={17} className="text-slate-400" />
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
