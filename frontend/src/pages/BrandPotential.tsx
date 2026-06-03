import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  ResponsiveContainer, RadialBarChart, RadialBar, PolarAngleAxis,
  BarChart, Bar, XAxis, YAxis, Tooltip, Cell,
} from "recharts";
import {
  Sparkles, TrendingUp, AlertTriangle, Activity, Rocket, MessagesSquare,
  RefreshCw, ChevronRight, ShieldCheck, Loader2, Users, Workflow, Info,
  CheckCircle2, XCircle, Clock,
} from "lucide-react";
import { apiClient } from "../api/client";
import { useLiveStream } from "../hooks/useLiveStream";

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
  manufacturer?: string;
  country?: string[];
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

const VERDICT_STYLE: Record<string, string> = {
  go: "bg-emerald-100 text-emerald-700 border-emerald-200",
  monitor: "bg-amber-100 text-amber-700 border-amber-200",
  hold: "bg-red-100 text-red-700 border-red-200",
};

const CHANNEL_ICON: Record<string, JSX.Element> = {
  paid: <TrendingUp size={12} />,
  organic: <Sparkles size={12} />,
  hcp: <Users size={12} />,
  comms: <MessagesSquare size={12} />,
  ops: <Workflow size={12} />,
};

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

function InsufficientData({ note }: { note?: string }) {
  return (
    <div className="relative w-full h-40 flex flex-col items-center justify-center text-center px-3">
      <span className="text-lg font-semibold text-slate-400">Insufficient data</span>
      <span className="mt-1 text-[10px] text-slate-500 uppercase tracking-wide">
        {note ?? "No mentions in window"}
      </span>
    </div>
  );
}

function ScoreRadial({ value, label }: { value: number; label: string }) {
  const data = [{ name: label, value, fill: scoreColour(value) }];
  return (
    <div className="relative w-full h-40">
      <ResponsiveContainer>
        <RadialBarChart innerRadius="66%" outerRadius="100%" data={data} startAngle={90} endAngle={-270}>
          <PolarAngleAxis type="number" domain={[0, 100]} angleAxisId={0} tick={false} />
          <RadialBar background dataKey="value" cornerRadius={10} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
        <span className="text-3xl font-bold text-slate-900 tabular-nums leading-none">{value.toFixed(0)}</span>
        <span className="mt-1 max-w-[6rem] truncate text-center text-[10px] text-slate-400 uppercase tracking-wide">{label}</span>
      </div>
    </div>
  );
}

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
  icon, title, subtitle, children,
}: { icon: JSX.Element; title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="bg-white border border-slate-200 rounded-2xl shadow-soft overflow-hidden">
      <div className="px-5 py-3.5 border-b border-slate-100 flex items-center gap-2.5 bg-gradient-to-br from-slate-50/50 to-transparent">
        <span className="shrink-0 w-7 h-7 rounded-lg bg-white border border-slate-200 flex items-center justify-center shadow-soft">
          {icon}
        </span>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
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
  const [country, setCountry] = useState<string>("");

  // 1. Brand list — populate the selector
  const { data: brands } = useQuery<Brand[]>({
    queryKey: ["brands-list"],
    queryFn: () => apiClient.get("/brands/").then((r) => r.data),
  });

  // Default to top brand once loaded
  useEffect(() => {
    if (brandId == null && brands && brands.length > 0) {
      setBrandId(brands[0].id);
    }
  }, [brands, brandId]);

  const params = useMemo(() => (country ? { country } : {}), [country]);

  const { data: bpi, isFetching: bpiLoading } = useQuery<Bundle>({
    queryKey: ["bpi", brandId, country],
    queryFn: () => apiClient.get(`/intelligence/bpi/${brandId}`, { params }).then((r) => r.data),
    enabled: brandId != null,
  });

  const { data: launch } = useQuery<Bundle>({
    queryKey: ["launch-readiness", brandId, country],
    queryFn: () => apiClient.get(`/intelligence/launch-readiness/${brandId}`, { params }).then((r) => r.data),
    enabled: brandId != null,
  });

  const { data: momentum } = useQuery<Bundle>({
    queryKey: ["momentum", brandId, country],
    queryFn: () => apiClient.get(`/intelligence/momentum/brand/${brandId}`, { params }).then((r) => r.data),
    enabled: brandId != null,
  });

  const { data: lifecycle } = useQuery<Bundle>({
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

  // Live ticker: subscribe to the mentions + signals channels so the user
  // sees Brand Potential update in real time as the bus fires.
  const liveMentions = useLiveStream<{ event?: string; text?: string; source_type?: string; country?: string; published_at?: string }>("mentions", { bufferSize: 8 });
  const liveSignals = useLiveStream<{ event?: string; entity_id?: number; entity_type?: string; score?: number; direction?: string }>("signals", { bufferSize: 8 });

  const { data: nba, refetch: refetchNba } = useQuery<Bundle>({
    queryKey: ["nba", brandId, country],
    queryFn: () => apiClient.get(`/intelligence/next-best-action/${brandId}`, { params }).then((r) => r.data),
    enabled: brandId != null,
  });

  const flywheelLog = useMutation({
    mutationFn: (payload: { subject_id: string; decision: string; context?: any }) =>
      apiClient.post("/intelligence/flywheel/log", {
        subject_type: "recommendation",
        ...payload,
      }),
  });

  const brandName = brands?.find((b) => b.id === brandId)?.name ?? "—";
  const bpiScore = bpi?.metrics[0]?.value ?? 0;
  const launchScore = launch?.metrics[0]?.value ?? 0;
  const verdict: string = launch?.context?.verdict ?? "—";
  const lifecycleStage: string = lifecycle?.context?.stage ?? "—";
  const momentumScore = momentum?.metrics[0]?.value ?? 0;
  // A score of 50 with no underlying mentions is the neutral fallback, not a real
  // assessment — surface that honestly instead of a misleading precise number.
  const bpiInsufficient = (bpi?.metrics[0]?.sample_size ?? 0) === 0;
  const launchInsufficient = (launch?.metrics[0]?.sample_size ?? 0) === 0;

  const componentBars = useMemo(() => {
    if (!bpi) return [];
    // skip the first metric (overall score), keep the four components
    return bpi.metrics.slice(1).map((m) => ({ name: m.label, value: m.value }));
  }, [bpi]);

  const topicBars = useMemo(() => {
    if (!keyMsg) return [];
    return keyMsg.metrics.slice(1).map((m) => ({
      name: m.label.replace(" resonance", ""),
      value: m.value,
    }));
  }, [keyMsg]);

  const nbaList: NBAItem[] = nba?.context?.actions ?? [];
  const pivotList: Array<{ trigger: string; action: string; severity: string; severity_score: number; evidence: any }> =
    pivots?.context?.pivots ?? [];

  const handleDecision = (item: NBAItem, decision: "accepted" | "skipped" | "acted_upon" | "dismissed") => {
    flywheelLog.mutate({
      subject_id: `${brandId}::${item.source_module}::${item.title.slice(0, 40)}`,
      decision,
      context: {
        brand_id: brandId,
        brand_name: brandName,
        source_module: item.source_module,
        priority_score: item.priority_score,
        category: item.channel,
      },
    });
    setTimeout(() => refetchNba(), 400);
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
              Brand Potential Index, Launch Readiness, Key Messages, Pivots, and Next-Best-Actions — TDAH composite.
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
              <option value="">All countries</option>
              <option value="BE">Belgium</option>
              <option value="FR">France</option>
              <option value="NL">Netherlands</option>
              <option value="DE">Germany</option>
            </select>
          </div>
        </div>
      </div>

      {bpiLoading && (
        <div className="flex items-center justify-center py-20 text-slate-400">
          <Loader2 className="animate-spin mr-2" size={18} /> Loading brand intelligence…
        </div>
      )}

      {brandId != null && !bpiLoading && (
        <>
          {/* Live stream ticker — proof that the bus is alive */}
          {(liveMentions.events.length > 0 || liveSignals.events.length > 0) && (
            <div className="bg-white border border-slate-200 rounded-2xl shadow-soft overflow-hidden">
              <div className="px-4 py-2 border-b border-slate-100 flex items-center gap-2 bg-gradient-to-r from-emerald-50/50 to-transparent">
                <span className="relative flex w-2.5 h-2.5">
                  <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60 animate-ping" />
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
                </span>
                <p className="text-xs font-semibold text-slate-700">Live stream</p>
                <span className="text-[10px] text-slate-400">
                  {liveMentions.events.length} mention{liveMentions.events.length === 1 ? "" : "s"} · {liveSignals.events.length} signal{liveSignals.events.length === 1 ? "" : "s"}
                </span>
              </div>
              <div className="px-4 py-2 flex gap-3 overflow-x-auto">
                {liveSignals.events.map((s, i) => (
                  <span key={`s-${i}`} className="shrink-0 text-[11px] inline-flex items-center gap-1.5 px-2 py-1 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
                    <AlertTriangle size={11} /> {s.event} {s.entity_type}#{s.entity_id} · {s.score?.toFixed(0) ?? "—"}
                  </span>
                ))}
                {liveMentions.events.map((m, i) => (
                  <span key={`m-${i}`} className="shrink-0 text-[11px] inline-flex items-center gap-1.5 px-2 py-1 rounded-full bg-slate-50 text-slate-600 border border-slate-200 max-w-xs truncate">
                    <Activity size={11} className="shrink-0 text-emerald-500" />
                    <span className="font-semibold">{m.source_type ?? "src"}</span>
                    {m.country && <span className="text-slate-400">· {m.country}</span>}
                    <span className="truncate">{(m.text ?? "").slice(0, 80)}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Top row — BPI + Launch Readiness + Momentum + Lifecycle */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <SectionCard icon={<Sparkles size={14} className="text-accent-600" />} title="BPI" subtitle="Awareness × Adoption × Sentiment × Fit">
              {bpiInsufficient ? (
                <InsufficientData />
              ) : (
                <>
                  <ScoreRadial value={bpiScore} label="BPI" />
                  <div className="mt-3 space-y-0.5">
                    {bpi?.metrics.slice(1).map((m) => (
                      <MetricRow key={m.label} label={m.label} value={m.value} unit={m.unit?.replace("0–100", "") ?? "%"} />
                    ))}
                  </div>
                </>
              )}
            </SectionCard>

            <SectionCard icon={<Rocket size={14} className="text-brand-600" />} title="Launch Readiness" subtitle="Composite of Phase 1 outputs">
              {launchInsufficient ? (
                <InsufficientData note="No recent mentions" />
              ) : (
                <>
                  <ScoreRadial value={launchScore} label={verdict.toUpperCase()} />
                  <div className="mt-3">
                    <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${VERDICT_STYLE[verdict] ?? "bg-slate-50 text-slate-500 border-slate-200"}`}>
                      Verdict: {verdict}
                    </span>
                  </div>
                  <div className="mt-3 space-y-0.5">
                    {launch?.metrics.slice(1).map((m) => (
                      <MetricRow key={m.label} label={m.label} value={m.value} unit="" />
                    ))}
                  </div>
                </>
              )}
            </SectionCard>

            <SectionCard icon={<TrendingUp size={14} className="text-emerald-600" />} title="Momentum" subtitle="Velocity + acceleration">
              <ScoreRadial value={momentumScore} label="Momentum" />
              <div className="mt-3 space-y-0.5">
                {momentum?.metrics.slice(1).map((m) => (
                  <MetricRow key={m.label} label={m.label} value={m.value} unit={m.unit ?? "%"} />
                ))}
              </div>
            </SectionCard>

            <SectionCard icon={<Activity size={14} className="text-violet-600" />} title="Lifecycle" subtitle="Stage classification">
              <div className="relative h-40 flex flex-col items-center justify-center">
                <span className="text-2xl font-bold text-slate-900 capitalize">{lifecycleStage.replace("_", " ")}</span>
                <span className="text-[10px] text-slate-400 uppercase tracking-wider mt-1">
                  velocity {fmt(lifecycle?.context?.velocity_pct, 1)}%
                </span>
              </div>
              <div className="mt-3 space-y-0.5">
                <MetricRow label="Total mentions" value={lifecycle?.context?.sample_size ?? lifecycle?.metrics[1]?.value ?? 0} />
                <MetricRow label="Positive share" value={(lifecycle?.context?.positive_share ?? 0) * 100} unit="%" />
                <MetricRow label="Confidence" value={(lifecycle?.metrics[0]?.confidence ?? 0) * 100} unit="%" />
              </div>
            </SectionCard>
          </div>

          {/* BPI components bar — extra detail */}
          <SectionCard icon={<Sparkles size={14} className="text-accent-600" />} title="BPI components" subtitle="Each component contributes equally to the geometric mean">
            <div className="h-44">
              <ResponsiveContainer>
                <BarChart data={componentBars} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#475569" }} axisLine={false} tickLine={false} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                  <Tooltip
                    contentStyle={{ fontSize: 11, padding: "6px 10px", borderRadius: 8, border: "1px solid #e2e8f0", boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }}
                    formatter={(v: number) => [`${v.toFixed(1)}%`, ""]}
                  />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                    {componentBars.map((d, i) => (
                      <Cell key={i} fill={scoreColour(d.value)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </SectionCard>

          {/* Key message tuning */}
          <SectionCard
            icon={<MessagesSquare size={14} className="text-indigo-600" />}
            title="Key Message Tuning"
            subtitle="Engagement-weighted resonance per topic. 50% baseline = neutral."
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

          {/* Campaign pivots */}
          <SectionCard icon={<AlertTriangle size={14} className="text-amber-600" />} title="Campaign Pivots" subtitle="Signal-triggered creative / spend changes">
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

          {/* HCP Targeting (graceful no-data) */}
          <SectionCard
            icon={<Users size={14} className="text-sky-600" />}
            title="HCP Targeting"
            subtitle="Prescriber momentum — requires KOL / Rx data source"
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

          {/* Next-Best-Actions */}
          <SectionCard
            icon={<Workflow size={14} className="text-violet-600" />}
            title="Next-Best-Action queue"
            subtitle="Composed across all modules · flywheel-weighted"
          >
            {nbaList.length === 0 ? (
              <p className="text-xs text-slate-400 py-6 text-center">No actions surfaced for this brand right now.</p>
            ) : (
              <ul className="space-y-2">
                {nbaList.map((a, i) => (
                  <li key={i} className="rounded-xl border border-slate-200 bg-white p-4">
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
                          <span className="text-[10px] text-slate-500 bg-slate-50 border border-slate-200 px-2 py-0.5 rounded-full inline-flex items-center gap-1">
                            {CHANNEL_ICON[a.channel] ?? null} {a.channel}
                          </span>
                          <span className="text-[10px] text-slate-500 bg-slate-50 border border-slate-200 px-2 py-0.5 rounded-full">{a.stakeholder}</span>
                          <span className="text-[10px] text-slate-400 ml-auto inline-flex items-center gap-1">
                            <RefreshCw size={9} /> flywheel ×{a.flywheel_multiplier.toFixed(2)}
                          </span>
                        </div>
                        <p className="text-xs text-slate-600 mt-1.5 leading-relaxed">{a.rationale}</p>
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
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {flywheelLog.isPending && (
              <p className="text-[11px] text-slate-400 mt-3 inline-flex items-center gap-1">
                <Loader2 size={11} className="animate-spin" /> Logging action to flywheel…
              </p>
            )}
          </SectionCard>
        </>
      )}
    </div>
  );
}
