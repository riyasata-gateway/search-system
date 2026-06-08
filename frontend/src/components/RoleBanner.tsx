import { useAuth } from "../hooks/useAuth";
import { themeFor } from "../lib/roleTheme";

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

/**
 * Role-aware welcome banner shown at the top of each role's landing dashboard.
 * Picks up the active role's identity + accent (see lib/roleTheme.ts) so every
 * persona is greeted with its own product framing, icon and colour wash.
 */
export default function RoleBanner({ aside }: { aside?: React.ReactNode }) {
  const { user } = useAuth();
  const t = themeFor(user?.role);
  const Icon = t.Icon;

  return (
    <div
      className="relative overflow-hidden rounded-2xl border border-white/10 px-5 py-4 flex items-center justify-between gap-4"
      style={{
        background: `linear-gradient(110deg, rgba(${t.accentRgb},0.16), rgba(${t.accentRgb},0.04) 55%, transparent)`,
      }}
    >
      {/* accent edge */}
      <span
        className="absolute left-0 top-0 bottom-0 w-1"
        style={{ background: `linear-gradient(${t.gradient[0]}, ${t.gradient[1]})` }}
      />
      <div className="flex items-center gap-4 min-w-0">
        <div
          className="shrink-0 w-11 h-11 rounded-xl flex items-center justify-center ring-1 ring-white/10"
          style={{ background: `linear-gradient(135deg, ${t.gradient[0]}, ${t.gradient[1]})` }}
        >
          <Icon size={22} className="text-white" strokeWidth={2.2} />
        </div>
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-wider" style={{ color: t.accent }}>
            {greeting()} · {t.product}
          </p>
          <p className="text-sm text-slate-300 truncate">{t.tagline}</p>
        </div>
      </div>
      {aside && <div className="shrink-0">{aside}</div>}
    </div>
  );
}