import {
  Radio, MessageSquare, Activity, Sparkles, ShieldAlert,
  CheckCircle2, Eye, Ban, TrendingUp, ExternalLink,
} from "lucide-react";
import { themeFor } from "../lib/roleTheme";
import type { Role } from "../hooks/useAuth";

/**
 * Per-role "cockpit" hero — the top-of-dashboard band that makes each role's
 * workspace structurally distinct, not just recoloured:
 *
 *   marketing      → a LISTENING cockpit  (reach · audience sentiment split · demand momentum)
 *   brand_manager  → a COMMAND cockpit    (Brand Potential Index · launch verdict · brand risk)
 *
 * Built in native light Tailwind (bg-white / text-gray-*) so the dark `.surface-app`
 * and light `.surface-light` reskin layers both render it correctly; the role
 * accent is injected inline from roleTheme so the band is unmistakably the role's.
 */
const VERDICT: Record<string, { label: string; cls: string; Icon: any }> = {
  go:      { label: "GO",      cls: "bg-emerald-100 text-emerald-700", Icon: CheckCircle2 },
  monitor: { label: "MONITOR", cls: "bg-amber-100 text-amber-700",     Icon: Eye },
  hold:    { label: "HOLD",    cls: "bg-red-100 text-red-700",         Icon: Ban },
};

function momentumWord(v: number | null) {
  if (v == null || v === 0) return "No signal";
  if (v >= 70) return "Strong";
  if (v >= 40) return "Moderate";
  return "Weak";
}

interface Props {
  view: "marketing" | "brand";
  role?: Role | string | null;
  totalMentions: number;
  positivePct: number;
  momentum: number | null;
  bpi: number | null;
  bpiInsufficient: boolean;
  bpiConfidence?: number | null;   // 0–1; surfaced as a confidence badge
  bpiFlywheel?: number | null;     // ± points the action-acceptance flywheel moved BPI
  launchVerdict?: string;
  launchScore: number | null;
  launchInsufficient: boolean;
  riskMentions: number;
  sentBreak: Record<string, number>;
  /** Review the brand's risk mentions (brand-scoped) — wired by the parent. */
  onRisk?: () => void;
}

function Tile({ children, accentRgb }: { children: React.ReactNode; accentRgb: string }) {
  return (
    <div
      className="bg-white rounded-xl border border-gray-200 p-5 relative overflow-hidden"
      style={{ boxShadow: `inset 3px 0 0 0 rgba(${accentRgb},0.55)` }}
    >
      {children}
    </div>
  );
}

export default function RoleHero(p: Props) {
  const t = themeFor(p.role);
  const accent = t.accent;
  const rgb = t.accentRgb;

  if (p.view === "marketing") {
    // LISTENING cockpit — reach, audience sentiment split, demand momentum.
    const total = p.sentBreak ? Object.values(p.sentBreak).reduce((a, b) => a + Number(b), 0) : 0;
    const seg = (k: string) => (total ? Math.round(((p.sentBreak?.[k] ?? 0) / total) * 100) : 0);
    const mv = p.momentum == null ? null : Math.round(p.momentum);
    return (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Tile accentRgb={rgb}>
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-500">Total Reach</span>
            <Radio size={18} style={{ color: accent }} />
          </div>
          <p className="text-3xl font-bold text-gray-900 mt-2 tabular-nums">{p.totalMentions.toLocaleString()}</p>
          <p className="text-xs text-gray-400 mt-1">mentions tracked · all sources</p>
        </Tile>

        <Tile accentRgb={rgb}>
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-500">Audience Sentiment</span>
            <MessageSquare size={18} style={{ color: accent }} />
          </div>
          <p className="text-3xl font-bold text-gray-900 mt-2 tabular-nums">{p.positivePct}<span className="text-base text-gray-400 ml-0.5">% positive</span></p>
          <div className="mt-3 flex h-2 w-full overflow-hidden rounded-full bg-gray-100">
            <span className="h-full bg-emerald-500" style={{ width: `${seg("positive")}%` }} />
            <span className="h-full bg-slate-400" style={{ width: `${seg("neutral")}%` }} />
            <span className="h-full bg-red-500" style={{ width: `${seg("negative")}%` }} />
          </div>
        </Tile>

        <Tile accentRgb={rgb}>
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-500">Demand Momentum</span>
            <Activity size={18} style={{ color: accent }} />
          </div>
          <p className="text-3xl font-bold text-gray-900 mt-2 tabular-nums">{mv ?? "—"}<span className="text-base text-gray-400 ml-0.5">/100</span></p>
          <p className="text-xs mt-1 font-medium" style={{ color: accent }}>{momentumWord(mv)}</p>
        </Tile>
      </div>
    );
  }

  // COMMAND cockpit — Brand Potential Index, launch verdict, brand risk.
  const v = p.launchVerdict ? (VERDICT[p.launchVerdict] ?? VERDICT.monitor) : null;
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {/* BPI — the strategic centrepiece */}
      <div
        className="rounded-xl border border-gray-200 p-5 relative overflow-hidden text-white md:row-span-1"
        style={{ background: `linear-gradient(135deg, ${t.gradient[0]}, ${t.gradient[1]})` }}
      >
        <div className="flex items-center justify-between">
          <span className="text-sm text-white/80">Brand Potential Index</span>
          <Sparkles size={18} className="text-white/90" />
        </div>
        <p className="text-4xl font-bold mt-2 tabular-nums">
          {p.bpiInsufficient ? "n/a" : (p.bpi == null ? "—" : Math.round(p.bpi))}
          {!p.bpiInsufficient && p.bpi != null && <span className="text-lg text-white/70 ml-1">/100</span>}
        </p>
        <p className="text-xs text-white/70 mt-1">
          composite · awareness × adoption × sentiment × fit
          {!p.bpiInsufficient && p.bpiConfidence != null && (
            <span className="ml-1.5 font-semibold text-white/90">· {Math.round(p.bpiConfidence * 100)}% confidence</span>
          )}
          {!p.bpiInsufficient && !!p.bpiFlywheel && (
            <span className="ml-1.5 font-semibold text-white/90" title="Adjustment from how your team accepts this brand's recommended actions (capped ±5)">
              · flywheel {p.bpiFlywheel > 0 ? "+" : ""}{p.bpiFlywheel}
            </span>
          )}
        </p>
      </div>

      <Tile accentRgb={rgb}>
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-500">Launch Readiness</span>
          <TrendingUp size={18} style={{ color: accent }} />
        </div>
        {p.launchInsufficient || !v ? (
          <p className="text-2xl font-bold text-gray-400 mt-3">Not scored</p>
        ) : (
          <>
            <span className={`inline-flex items-center gap-1.5 mt-3 px-2.5 py-1 rounded-lg text-sm font-bold ${v.cls}`}>
              <v.Icon size={15} /> {v.label}
            </span>
            <p className="text-xs text-gray-400 mt-2 tabular-nums">{p.launchScore == null ? "" : `${Math.round(p.launchScore)}/100 readiness`}</p>
          </>
        )}
      </Tile>

      <Tile accentRgb={rgb}>
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-500">Brand Risk</span>
          <ShieldAlert size={18} className={p.riskMentions > 0 ? "text-red-500" : ""} style={p.riskMentions > 0 ? undefined : { color: accent }} />
        </div>
        <p className="text-3xl font-bold text-gray-900 mt-2 tabular-nums">{p.riskMentions}</p>
        <p className="text-xs text-gray-400 mt-1">risk {p.riskMentions === 1 ? "mention" : "mentions"} for this brand</p>
        {p.onRisk && p.riskMentions > 0 && (
          <button onClick={p.onRisk} className="mt-2 inline-flex items-center gap-1 text-xs font-medium hover:underline" style={{ color: accent }}>
            Review <ExternalLink size={11} />
          </button>
        )}
      </Tile>
    </div>
  );
}