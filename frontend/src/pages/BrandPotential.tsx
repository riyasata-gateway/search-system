import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell,
} from "recharts";
import {
  Sparkles, TrendingUp, AlertTriangle, Activity, MessagesSquare,
  RefreshCw, ChevronRight, ShieldCheck, Loader2, Users, Workflow, Info,
  CheckCircle2, XCircle, Clock,
} from "lucide-react";
import { apiClient } from "../api/client";
import InfoTip from "../components/InfoTip";
import { define } from "../lib/glossary";

// ── types ────────────────────────────────────────────────────────────────────

interface MetricEnvelope {
  kind: "abs" | "percent" | "score";
  value: number;
  label: string;
  unit?: string;
  delta?: number | null;
  confidence?: number | null;
  sample_size?: number | null;
}

interface Bundle {
  name: string;
  metrics: MetricEnvelope[];
  context: Record<string, any>;
}

interface Brand {
  id: number;
  name: string;
  category?: string | null;
  manufacturer?: string;
  has_data?: boolean;
  is_medicine?: boolean;
}

interface NBAItem {
  title: string;
  rationale: string;
  channel: string;
  stakeholder: string;
  priority_score: number;
  flywheel_multiplier: number;
  severity: "high" | "medium" | "low";
  source_module: string;
  evidence: Record<string, any>;
}

// ── helpers ──────────────────────────────────────────────────────────────────

const SEVERITY_STYLE: Record<string, string> = {
  high: "text-red-700 bg-red-50 border-red-200",
  medium: "text-amber-700 bg-amber-50 border-amber-200",
  low: "text-slate-600 bg-slate-50 border-slate-200",
};

const CHANNEL_ICON: Record<string, JSX.Element> = {
  paid: <TrendingUp size={12} />,
  organic: <Sparkles size={12} />,
  hcp: <Users size={12} />,
  comms: <MessagesSquare size={12} />,
  ops: <Workflow size={12} />,
};

// Human-readable labels for the engine's channel / stakeholder codes.
const CHANNEL_LABEL: Record<string, string> = {
  paid: "Paid media", organic: "Organic / SEO", hcp: "HCP / medical",
  comms: "Comms & PR", ops: "Operations",
};
const STAKEHOLDER_LABEL: Record<string, string> = {
  marketing: "Marketing team", brand: "Brand management", medical: "Medical affairs",
  sales: "Sales / trade", ops: "Operations", regulatory: "Regulatory",
};
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function scoreColour(v: number) {
  if (v >= 70) return "#10b981";
  if (v >= 40) return "#f59e0b";
  return "#ef4444";
}

function fmt(n?: number | null, d = 0) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toFixed(d);
}

// ── small components ─────────────────────────────────────────────────────────

function MetricRow({ label, value, unit }: { label: string; value: number; unit?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2 py-1.5 border-b border-slate-100 last:border-0">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-sm font-semibold text-slate-800 tabular-nums">
        {value.toFixed(1)}<span className="text-[10px] text-slate-400 ml-0.5">{unit ?? ""}</span>
      </span>
    </div>
  );
}

function SectionCard({
  icon, title, subtitle, info, children,
}: { icon: JSX.Element; title: string; subtitle?: string; info?: string; children: React.ReactNode }) {
  return (
    <div className="bg-white border border-slate-200 rounded-2xl shadow-soft overflow-hidden">
      <div className="px-5 py-3.5 border-b border-slate-100 flex items-center gap-2.5 bg-white/[0.02]">
        <span className="shrink-0 w-7 h-7 rounded-lg bg-white border border-slate-200 flex items-center justify-center shadow-soft">
          {icon}
        </span>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-1.5">
            {title}{info && <InfoTip text={info} label={title} />}
          </h3>
          {subtitle && <p className="text-[11px] text-slate-400">{subtitle}</p>}
        </div>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

// ── main page ────────────────────────────────────────────────────────────────

export default function BrandPotential() {
  const [brandId, setBrandId] = useState<number | null>(null);
  // Product market is Belgium — default the lens there.
  const [country, setCountry] = useState<string>("BE");
  // Optimistic local state so action buttons give immediate feedback.
  const [decided, setDecided] = useState<Record<string, string>>({});

  // 1. Brand list — the role's tracked (framework) brands, which actually have
  //    linked data. (The legacy all-brands list included seed brands like Advil
  //    with zero mentions, so every engine came back empty.)
  const { data: brandResp } = useQuery<{ brands: Brand[] }>({
    queryKey: ["catalog-my-brands"],
    queryFn: () => apiClient.get("/catalog/my-brands").then((r) => r.data),
  });
  const brands = brandResp?.brands ?? [];

  // Default to the first brand that has data once loaded.
  useEffect(() => {
    if (brandId == null && brands.length > 0) {
      const withData = brands.find((b) => b.has_data);
      setBrandId((withData ?? brands[0]).id);
    }
  }, [brands, brandId]);

  const params = useMemo(() => (country ? { country } : {}), [country]);

  const { data: lifecycle, isFetching: lifecycleLoading } = useQuery<Bundle>({
    queryKey: ["lifecycle", brandId, country],
    queryFn: () => apiClient.get(`/intelligence/lifecycle/brand/${brandId}`, { params }).then((r) => r.data),
    enabled: brandId != null,
  });

  const { data: keyMsg } = useQuery<Bundle>({
    queryKey: ["key-messages", brandId, country],
    queryFn: () => apiClient.get(`/intelligence/key-messages/${brandId}`, { params }).then((r) => r.data),
    enabled: brandId != null,
  });

  const { data: pivots } = useQuery<Bundle>({
    queryKey: ["pivots", brandId, country],
    queryFn: () => apiClient.get(`/intelligence/campaign-pivots/${brandId}`, { params }).then((r) => r.data),
    enabled: brandId != null,
  });

  const { data: hcp } = useQuery<Bundle>({
    queryKey: ["hcp", brandId, country],
    queryFn: () => apiClient.get(`/intelligence/hcp-targeting/${brandId}`, { params }).then((r) => r.data),
    enabled: brandId != null,
  });

  // Analysis-driven actions — generated from this brand's live KPIs (catalog),
  // not the templated engine.
  const { data: nba, refetch: refetchNba } = useQuery<any>({
    queryKey: ["brand-actions", brandId],
    queryFn: () => apiClient.get(`/catalog/brand-actions`, { params: { brand_id: brandId } }).then((r) => r.data),
    enabled: brandId != null,
  });

  // Brand-specific HCP target derived from the SAM ATC code.
  const { data: hcpTarget } = useQuery<any>({
    queryKey: ["hcp-target", brandId],
    queryFn: () => apiClient.get("/catalog/hcp-target", { params: { brand_id: brandId } }).then((r) => r.data),
    enabled: brandId != null,
  });

  const flywheelLog = useMutation({
    mutationFn: (payload: { subject_id: string; decision: string; context?: any }) =>
      apiClient.post("/intelligence/flywheel/log", {
        subject_type: "recommendation",
        ...payload,
      }),
  });

  const selectedBrand = brands?.find((b) => b.id === brandId);
  const brandName = selectedBrand?.name ?? "—";
  const isMedicine = selectedBrand?.is_medicine ?? true; // default permissive until loaded
  const lifecycleStage: string = lifecycle?.context?.stage ?? "—";

  const topicBars = useMemo(() => {
    if (!keyMsg) return [];
    return keyMsg.metrics.slice(1).map((m) => ({
      name: m.label.replace(" resonance", ""),
      value: m.value,
    }));
  }, [keyMsg]);

  const nbaList: NBAItem[] = nba?.actions ?? [];
  const pivotList: Array<{ trigger: string; action: string; severity: string; severity_score: number; evidence: any }> =
    pivots?.context?.pivots ?? [];

  const actionKey = (item: NBAItem) => `${brandId}::${item.source_module}::${item.title.slice(0, 40)}`;

  const handleDecision = (item: NBAItem, decision: "accepted" | "skipped" | "acted_upon" | "dismissed") => {
    // Optimistically record the decision so the card reflects it immediately —
    // the flywheel log is fire-and-forget and the NBA engine recomputes the same
    // queue, so without this the buttons looked unresponsive.
    setDecided((prev) => ({ ...prev, [actionKey(item)]: decision }));
    flywheelLog.mutate({
      subject_id: actionKey(item),
      decision,
      context: {
        brand_id: brandId,
        brand_name: brandName,
        source_module: item.source_module,
        priority_score: item.priority_score,
        category: item.channel,
      },
    });
    // dismissed/skipped drop out of view; accepted/acted stay shown as resolved.
    setTimeout(() => refetchNba(), 600);
  };

  const DECISION_BADGE: Record<string, string> = {
    accepted: "bg-emerald-500/15 text-emerald-300 border-emerald-400/40",
    acted_upon: "bg-violet-500/15 text-violet-300 border-violet-400/40",
    skipped: "bg-white/10 text-slate-400 border-white/20",
    dismissed: "bg-red-500/15 text-red-300 border-red-400/40",
  };

  return (
    <div className="space-y-6 max-w-7xl animate-fade-up">
      {/* Header */}
      <div className="relative rounded-2xl overflow-hidden border border-slate-200/70 bg-white shadow-soft">
        <div className="absolute inset-0 bg-gradient-to-br from-accent-500/10 via-transparent to-brand-500/10 pointer-events-none" />
        <div className="relative px-6 py-5 flex flex-wrap items-center gap-4">
          <div className="shrink-0 w-11 h-11 rounded-xl bg-gradient-to-br from-accent-500 to-brand-500 flex items-center justify-center shadow-elevated">
            <Sparkles size={20} className="text-white" strokeWidth={2.4} />
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Brand Potential</h1>
            <p className="text-sm text-slate-500 mt-0.5">
              The action layer — Next-Best-Actions, message tuning, campaign pivots, lifecycle and HCP targeting.
              <span className="text-slate-400"> See Brand Pulse for the at-a-glance scores.</span>
            </p>
          </div>

          {/* Brand + country selectors */}
          <div className="flex flex-wrap gap-2">
            <select
              value={brandId ?? ""}
              onChange={(e) => setBrandId(Number(e.target.value))}
              className="px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm shadow-soft focus:outline-none focus:border-accent-400"
            >
              {brands?.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
            <select
              value={country}
              onChange={(e) => setCountry(e.target.value)}
              className="px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm shadow-soft focus:outline-none focus:border-accent-400"
            >
              <option value="BE">Belgium</option>
              <option value="">All countries</option>
              <option value="FR">France</option>
              <option value="NL">Netherlands</option>
            </select>
          </div>
        </div>
      </div>

      {lifecycleLoading && brandId != null && nbaList.length === 0 && (
        <div className="flex items-center justify-center py-20 text-slate-400">
          <Loader2 className="animate-spin mr-2" size={18} /> Loading brand intelligence…
        </div>
      )}

      {brandId != null && (
        <>
          {/* Next-Best-Actions — the headline of the action layer */}
          <SectionCard
            icon={<Workflow size={14} className="text-violet-600" />}
            title="Next-Best-Action queue"
            subtitle="Composed across all modules · flywheel-weighted"
            info={define("Next-Best-Action")}
          >
            {nbaList.length === 0 ? (
              <p className="text-xs text-slate-400 py-6 text-center">No actions surfaced for this brand right now.</p>
            ) : (
              <ul className="space-y-2">
                {nbaList.map((a, i) => {
                  const decision = decided[actionKey(a)];
                  const resolved = !!decision;
                  return (
                  <li key={i} className={`rounded-xl border border-slate-200 bg-white p-4 transition-opacity ${resolved ? "opacity-60" : ""}`}>
                    <div className="flex items-start gap-3">
                      <span
                        className="shrink-0 inline-flex items-center justify-center w-9 h-9 rounded-lg text-white text-xs font-bold tabular-nums shadow-soft"
                        style={{ backgroundColor: scoreColour(a.priority_score) }}
                      >
                        {a.priority_score.toFixed(0)}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <p className="text-sm font-semibold text-slate-900">{a.title}</p>
                          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${SEVERITY_STYLE[a.severity]}`}>{a.severity}</span>
                          <span className="text-[10px] text-slate-500 bg-slate-50 border border-slate-200 px-2 py-0.5 rounded-full inline-flex items-center gap-1" title="Channel where this action runs">
                            {CHANNEL_ICON[a.channel] ?? null} {CHANNEL_LABEL[a.channel] ?? cap(a.channel)}
                          </span>
                          <span className="text-[10px] text-slate-500 bg-slate-50 border border-slate-200 px-2 py-0.5 rounded-full" title="Team that owns this action">
                            Owner: {STAKEHOLDER_LABEL[a.stakeholder] ?? cap(a.stakeholder)}
                          </span>
                          <span className="text-[10px] text-slate-400 ml-auto inline-flex items-center gap-1">
                            <RefreshCw size={9} /> flywheel ×{a.flywheel_multiplier.toFixed(2)}
                          </span>
                        </div>
                        <p className="text-xs text-slate-600 mt-1.5 leading-relaxed">{a.rationale}</p>
                        {resolved ? (
                          <div className="flex items-center gap-2 mt-3">
                            <span className={`inline-flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-lg border capitalize ${DECISION_BADGE[decision] ?? "bg-white/10 text-slate-300 border-white/20"}`}>
                              <CheckCircle2 size={12} /> {decision.replace("_", " ")}
                            </span>
                            <button
                              onClick={() => setDecided((prev) => { const n = { ...prev }; delete n[actionKey(a)]; return n; })}
                              className="text-[11px] text-slate-400 hover:text-slate-200 underline"
                            >
                              Undo
                            </button>
                          </div>
                        ) : (
                          <div className="flex flex-wrap items-center gap-2 mt-3">
                            <button
                              onClick={() => handleDecision(a, "accepted")}
                              className="inline-flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white shadow-soft"
                            >
                              <CheckCircle2 size={12} /> Accept
                            </button>
                            <button
                              onClick={() => handleDecision(a, "acted_upon")}
                              className="inline-flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-700 text-white shadow-soft"
                            >
                              <ShieldCheck size={12} /> Mark as acted
                            </button>
                            <button
                              onClick={() => handleDecision(a, "skipped")}
                              className="inline-flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50"
                            >
                              <Clock size={12} /> Skip
                            </button>
                            <button
                              onClick={() => handleDecision(a, "dismissed")}
                              className="inline-flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50"
                            >
                              <XCircle size={12} /> Dismiss
                            </button>
                            <span className="text-[10px] text-slate-400 ml-1 inline-flex items-center gap-1">
                              <ChevronRight size={10} /> {a.source_module}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  </li>
                  );
                })}
              </ul>
            )}
            {flywheelLog.isPending && (
              <p className="text-[11px] text-slate-400 mt-3 inline-flex items-center gap-1">
                <Loader2 size={11} className="animate-spin" /> Logging action to flywheel…
              </p>
            )}
          </SectionCard>

          {/* Lifecycle + Key message tuning */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <SectionCard icon={<Activity size={14} className="text-violet-600" />} title="Lifecycle" subtitle="Stage classification" info={define("Lifecycle")}>
              <div className="relative h-32 flex flex-col items-center justify-center">
                <span className="text-2xl font-bold text-slate-900 capitalize">{lifecycleStage.replace("_", " ")}</span>
                <span className="text-[10px] text-slate-400 uppercase tracking-wider mt-1">
                  velocity {fmt(lifecycle?.context?.velocity_pct, 1)}%
                </span>
              </div>
              <div className="mt-3 space-y-0.5">
                <MetricRow label="Total mentions" value={lifecycle?.context?.sample_size ?? lifecycle?.metrics?.[1]?.value ?? 0} />
                <MetricRow label="Positive share" value={(lifecycle?.context?.positive_share ?? 0) * 100} unit="%" />
                <MetricRow label="Confidence" value={(lifecycle?.metrics?.[0]?.confidence ?? 0) * 100} unit="%" />
              </div>
            </SectionCard>

            <div className="lg:col-span-2">
              <SectionCard
                icon={<MessagesSquare size={14} className="text-indigo-600" />}
                title="Key Message Tuning"
                subtitle="Engagement-weighted resonance per topic. 50% baseline = neutral."
                info={define("Key Message Tuning")}
              >
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                  <div className="lg:col-span-2 h-44">
                    {topicBars.length === 0 ? (
                      <p className="text-xs text-slate-400 h-full flex items-center justify-center">Not enough classified mentions to compute resonance.</p>
                    ) : (
                      <ResponsiveContainer>
                        <BarChart data={topicBars} layout="vertical" margin={{ top: 0, right: 10, left: 4, bottom: 0 }}>
                          <XAxis type="number" domain={[0, 100]} hide />
                          <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: "#475569" }} axisLine={false} tickLine={false} width={80} />
                          <Tooltip
                            contentStyle={{ fontSize: 11, padding: "6px 10px", borderRadius: 8, border: "1px solid #e2e8f0" }}
                            formatter={(v: number) => [`${v.toFixed(1)}%`, "Resonance"]}
                          />
                          <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={12}>
                            {topicBars.map((d, i) => (
                              <Cell key={i} fill={scoreColour(d.value)} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                  <div className="space-y-2">
                    <div>
                      <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Winning</p>
                      <div className="flex flex-wrap gap-1.5">
                        {(keyMsg?.context?.winning ?? []).length === 0
                          ? <span className="text-xs text-slate-400">—</span>
                          : (keyMsg?.context?.winning ?? []).map((t: string) => (
                              <span key={t} className="text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">{t}</span>
                            ))
                        }
                      </div>
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Losing</p>
                      <div className="flex flex-wrap gap-1.5">
                        {(keyMsg?.context?.losing ?? []).length === 0
                          ? <span className="text-xs text-slate-400">—</span>
                          : (keyMsg?.context?.losing ?? []).map((t: string) => (
                              <span key={t} className="text-xs px-2 py-0.5 rounded-full bg-red-50 text-red-700 border border-red-200">{t}</span>
                            ))
                        }
                      </div>
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Underexposed</p>
                      <div className="flex flex-wrap gap-1.5">
                        {(keyMsg?.context?.underexposed ?? []).length === 0
                          ? <span className="text-xs text-slate-400">—</span>
                          : (keyMsg?.context?.underexposed ?? []).map((t: string) => (
                              <span key={t} className="text-xs px-2 py-0.5 rounded-full bg-slate-50 text-slate-600 border border-slate-200">{t}</span>
                            ))
                        }
                      </div>
                    </div>
                  </div>
                </div>
              </SectionCard>
            </div>
          </div>

          {/* Campaign pivots */}
          <SectionCard icon={<AlertTriangle size={14} className="text-amber-600" />} title="Campaign Pivots" subtitle="Signal-triggered creative / spend changes" info={define("Campaign Pivots")}>
            {pivotList.length === 0 ? (
              <p className="text-xs text-slate-400 py-6 text-center">No pivots triggered — current signal is stable.</p>
            ) : (
              <ul className="space-y-2">
                {pivotList.map((p, i) => (
                  <li key={i} className={`rounded-xl border p-3.5 flex items-start gap-3 ${SEVERITY_STYLE[p.severity] ?? "border-slate-200 bg-white"}`}>
                    <AlertTriangle size={16} className="shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold">{p.trigger}</p>
                      <p className="text-xs mt-0.5 leading-relaxed">{p.action}</p>
                      <p className="text-[10px] mt-1 opacity-70">
                        Severity: {p.severity} · score {p.severity_score.toFixed(0)}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>

          {/* HCP Targeting — prescription-medicine concept only; hidden for parapharmacy */}
          {!isMedicine ? (
            <SectionCard
              icon={<Users size={14} className="text-slate-500" />}
              title="HCP Targeting"
              subtitle="Prescriber outreach"
              info={define("HCP Targeting")}
            >
              <div className="flex items-start gap-3 bg-white/[0.03] border border-dashed border-white/15 rounded-xl p-4">
                <Info size={16} className="text-slate-500 shrink-0 mt-0.5" />
                <p className="text-xs text-slate-400">
                  Not applicable — <span className="text-slate-200">{brandName}</span> is a parapharmacy/cosmetic
                  product (per the Belgian SAM register), so there are no prescribers to target. HCP targeting
                  applies to prescription medicines.
                </p>
              </div>
            </SectionCard>
          ) : (
          <SectionCard
            icon={<Users size={14} className="text-sky-600" />}
            title="HCP Targeting"
            subtitle="Prescriber momentum — requires KOL / Rx data source"
            info={define("HCP Targeting")}
          >
            {hcp?.context?.status === "available" && (hcp.context.targets?.length ?? 0) > 0 ? (
              <ul className="space-y-2">
                {hcp.context.targets.map((t: any) => (
                  <li key={t.hcp_id} className="rounded-xl border border-slate-200 bg-white p-3.5 flex items-center gap-3">
                    <Users size={16} className="text-sky-500 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-slate-900">{t.name}</p>
                      <p className="text-xs text-slate-500">{t.specialty} · {t.region}</p>
                    </div>
                    <span className="text-xs font-semibold text-sky-700 bg-sky-50 px-2.5 py-1 rounded-full border border-sky-200">
                      momentum {t.prescriber_momentum.toFixed(0)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : hcpTarget?.target ? (
              <div className="rounded-xl border border-sky-200 bg-sky-50/60 p-4">
                <p className="text-sm text-slate-800">
                  Target group: <span className="font-semibold text-sky-700">{hcpTarget.target.specialty}</span>
                </p>
                <p className="text-xs text-slate-600 mt-1">
                  Derived from the brand's active substance{hcpTarget.target.substance ? ` (${hcpTarget.target.substance})` : ""} —
                  ATC <span className="font-mono">{hcpTarget.target.atc}</span>
                  {hcpTarget.target.atc_desc ? ` · ${hcpTarget.target.atc_desc}` : ""}, from the Belgian SAM register.
                </p>
                <p className="text-[11px] text-slate-500 mt-2">
                  Connect <span className="text-slate-700">{hcpTarget.register}</span> to pull the named prescriber list for this specialty.
                </p>
              </div>
            ) : (
              <div className="flex items-start gap-3 bg-slate-50 border border-slate-200 rounded-xl p-4">
                <Info size={16} className="text-slate-500 shrink-0 mt-0.5" />
                <div className="flex-1 text-xs text-slate-600 space-y-1">
                  <p className="font-semibold text-slate-700">{hcp?.context?.message ?? "HCP data not available."}</p>
                  {hcp?.context?.next_step_for_admin && (
                    <p className="text-slate-500">{hcp.context.next_step_for_admin}</p>
                  )}
                </div>
              </div>
            )}
          </SectionCard>
          )}
        </>
      )}
    </div>
  );
}
