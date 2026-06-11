import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import {
  TrendingUp, Search, Loader2, ExternalLink,
  Megaphone, Briefcase,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import FrameworkKpiSection from "../components/FrameworkKpiSection";
import BrandPicker from "../components/BrandPicker";
import { useSelectedBrand } from "../lib/selectedBrand";
import ExportPdfButton from "../components/ExportPdfButton";
import RoleBanner from "../components/RoleBanner";
import RoleHero from "../components/RoleHero";
import InfoTip from "../components/InfoTip";
import { define } from "../lib/glossary";

const SENTIMENT_COLOURS: Record<string, string> = {
  positive: "#22c55e",
  neutral: "#94a3b8",
  negative: "#ef4444",
};

const TOPIC_COLOURS = ["#3b82f6", "#8b5cf6", "#f59e0b", "#10b981", "#f43f5e", "#06b6d4", "#84cc16"];


// ── data hooks (all brand-scoped via ?brand_id) ──────────────────────────────
function brandParam(brandId: number | null) {
  return brandId ? { brand_id: brandId } : {};
}

function useDashboard(brandId: number | null) {
  return useQuery({
    queryKey: ["lab-dashboard", brandId],
    queryFn: () => apiClient.get("/lab/dashboard", { params: brandParam(brandId) }).then((r) => r.data),
    enabled: brandId != null,
  });
}

function useWeeklySummary(brandId: number | null) {
  return useQuery({
    queryKey: ["weekly-summary", brandId],
    queryFn: () => apiClient.get("/lab/weekly-summary", { params: brandParam(brandId) }).then((r) => r.data),
    staleTime: 3_600_000,
    enabled: brandId != null,
  });
}

function useSentimentBreakdown(brandId: number | null) {
  return useQuery({
    queryKey: ["sentiment-breakdown", brandId],
    queryFn: () => apiClient.get("/lab/sentiment-breakdown", { params: brandParam(brandId) }).then((r) => r.data),
    enabled: brandId != null,
  });
}

function useTopicClusters(brandId: number | null) {
  return useQuery({
    queryKey: ["topic-clusters", brandId],
    queryFn: () => apiClient.get("/lab/topic-clusters", { params: brandParam(brandId) }).then((r) => r.data),
    enabled: brandId != null,
  });
}

function useIntel(path: string, brandId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: ["intel", path, brandId],
    queryFn: () => apiClient.get(`/intelligence/${path}/${brandId}`).then((r) => r.data),
    enabled: enabled && brandId != null,
    retry: false,
  });
}

function useLiveCompetitor(brand: string, enabled: boolean) {
  return useQuery({
    queryKey: ["live-competitor", brand],
    queryFn: () =>
      apiClient
        .get("/search/live", { params: { q: brand, sources: "news", period: "30d" }, timeout: 25_000 })
        .then((r) => r.data),
    enabled: enabled && brand.length >= 2,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

const headline = (bundle: any) => bundle?.metrics?.[0] ?? null;
const fmt = (v: any) => (v == null ? "—" : typeof v === "number" ? Math.round(v) : v);

// ── small presentational helpers ─────────────────────────────────────────────

// A small labelled statistic (replaces the old horizontal gauge bars).
// Explicit translucent-white fill so it stays visible on the dark canvas.
// Look up a glossary definition for a metric label, normalising variants like
// "Lifecycle: unknown" → "Lifecycle" and "Adoption (proxy)" → "Adoption".
const metricDef = (label: string) =>
  define((label || "").split(":")[0].replace(/\s*\(proxy\)/i, "").trim());

function StatTile({ label, value, unit, info }: { label: string; value: number | null; unit?: string; info?: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.05] px-3 py-2">
      <p className="text-[11px] text-slate-400 leading-tight flex items-center gap-1">
        {label}{info ? <InfoTip text={info} label={label} /> : null}
      </p>
      <p className="text-lg font-bold text-white tabular-nums leading-tight mt-0.5">
        {fmt(value)}<span className="text-[11px] font-medium text-slate-400 ml-0.5">{unit ?? ""}</span>
      </p>
    </div>
  );
}

export default function BrandPulse() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const role = user?.role ?? "brand_manager";

  // marketing → reach/resonance view; brand_manager → market/risk view; admin → toggle.
  const [adminView, setAdminView] = useState<"marketing" | "brand">("brand");
  const view = role === "marketing" ? "marketing" : role === "brand_manager" ? "brand" : adminView;
  const isMarketing = view === "marketing";
  // Admins view-as a role; everyone else is locked to their own role server-side.
  const frameworkRole = role === "admin" ? (isMarketing ? "marketing" : "brand_manager") : undefined;

  // Shared across pages — the brand picked here carries to Brand Potential.
  const [activeBrand, setActiveBrand] = useSelectedBrand();
  const brandId = activeBrand?.id ?? null;

  const [competitorInput, setCompetitorInput] = useState("");
  const [competitorQuery, setCompetitorQuery] = useState("");

  const { data: dashboard, isLoading } = useDashboard(brandId);
  const { data: summary } = useWeeklySummary(brandId);
  const { data: sentiment } = useSentimentBreakdown(brandId);
  const { data: topics } = useTopicClusters(brandId);

  // role-specific intelligence
  const { data: bpi } = useIntel("bpi", brandId, !isMarketing);
  const { data: launch } = useIntel("launch-readiness", brandId, !isMarketing);
  const { data: momentum } = useIntel("momentum/brand", brandId, true);
  const { data: keyMsg } = useIntel("key-messages", brandId, isMarketing);

  const { data: liveCompetitor, isFetching: competitorFetching } = useLiveCompetitor(competitorQuery, competitorQuery.length >= 2);

  const sentimentPieData = (sentiment ?? []).map((s: any) => ({ name: s.topic, value: s.count }));
  const topicBarData = (topics ?? []).slice(0, 8).map((t: any) => ({
    name: t.topic?.replace("_", " "),
    count: t.count,
  }));

  const totalMentions = dashboard?.total_mentions ?? 0;
  const riskMentions = dashboard?.risk_alert_count ?? 0;
  const sentBreak = dashboard?.sentiment_breakdown ?? {};
  const sentTotal = Object.values(sentBreak).reduce((a: number, b: any) => a + Number(b), 0) || 1;
  const positivePct = Math.round(((sentBreak.positive ?? 0) / sentTotal) * 100);

  const bpiHead = headline(bpi);
  const launchHead = headline(launch);
  const momentumHead = headline(momentum);
  // BPI sub-scores (Awareness × Adoption × Sentiment × Fit). Each carries a
  // status so a neutral-fallback 50 or sole-brand 100 isn't shown as a real score.
  const bpiStatus = bpi?.context?.component_status ?? {};
  const statusKey = (label: string) => {
    const l = (label || "").toLowerCase();
    if (l.startsWith("aware")) return "awareness";
    if (l.startsWith("adopt")) return "adoption";
    if (l.startsWith("sentiment")) return "sentiment";
    if (l.startsWith("market")) return "market_fit";
    return "";
  };
  const bpiComponents = (bpi?.metrics ?? []).slice(1).map((m: any) => ({
    axis: m.label,
    value: m.value,
    status: bpiStatus[statusKey(m.label)] ?? "ok",
  }));
  const launchVerdict: string | undefined = launch?.context?.verdict;
  // No mentions in window, or nothing measurable (every component a fallback) →
  // the score isn't a real reading, so show "Insufficient data" not a number.
  const bpiInsufficient = (bpiHead?.sample_size ?? 0) === 0 || bpi?.context?.insufficient === true;
  const launchInsufficient = (launchHead?.sample_size ?? 0) === 0;
  const keyHead = headline(keyMsg);
  const winning = keyMsg?.context?.winning ?? [];
  const losing = keyMsg?.context?.losing ?? [];

  if (isLoading && brandId != null) return <div className="text-gray-500 text-sm">Loading dashboard…</div>;

  // Per-role section ORDER (CSS order on a flex column). Header/hero/role-panel
  // stay at the top (order 0); the shared sections re-sequence by role:
  //  • marketing (listening): lead with sentiment+topics charts → competitor →
  //    framework KPIs → exec summary.
  //  • brand_manager (command): lead with framework KPIs → competitor → exec
  //    summary, and push the listening charts to the bottom (secondary).
  const ord = isMarketing
    ? { charts: 1, competitor: 2, framework: 3, exec: 4, cta: 5 }
    : { framework: 1, competitor: 2, exec: 3, charts: 4, cta: 5 };

  return (
    <div id="brandpulse-export" className="flex flex-col gap-6">
      <RoleBanner />
      {/* Header: role-framed title + brand switcher + (admin) view toggle */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            {isMarketing ? <Megaphone size={22} className="text-amber-500" /> : <Briefcase size={22} className="text-purple-600" />}
            {isMarketing ? "Marketing — Reach & Resonance" : "Brand — Market & Risk"}
          </h1>
          <p className="text-sm text-gray-500">
            {isMarketing
              ? "Buzz, sentiment, message resonance and reach for your brand."
              : "Brand potential, launch readiness, demand and brand-risk signals."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {role === "admin" && (
            <div className="flex rounded-lg border border-gray-300 overflow-hidden text-sm">
              <button
                onClick={() => setAdminView("marketing")}
                className={`px-3 py-2 flex items-center gap-1.5 ${isMarketing ? "bg-amber-500 text-white" : "bg-white text-gray-600"}`}
              >
                <Megaphone size={14} /> Marketing
              </button>
              <button
                onClick={() => setAdminView("brand")}
                className={`px-3 py-2 flex items-center gap-1.5 ${!isMarketing ? "bg-purple-600 text-white" : "bg-white text-gray-600"}`}
              >
                <Briefcase size={14} /> Brand
              </button>
            </div>
          )}
          <BrandPicker
            value={brandId}
            selectedBrand={activeBrand}
            onSelect={(b) => setActiveBrand(b)}
          />
          <ExportPdfButton
            targetId="brandpulse-export"
            filename={`Brand Pulse — ${activeBrand?.name ?? "brand"}.pdf`}
          />
        </div>
      </div>

      {activeBrand && !activeBrand.has_data && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-2.5 text-sm text-amber-800">
          No mentions linked to <strong>{activeBrand.name}</strong> yet — this brand will populate as the corpus grows.
        </div>
      )}

      {/* Per-role cockpit hero — structurally distinct per role (listening vs
          command), not just recoloured. Marketing's reach/sentiment/momentum and
          brand-manager's BPI/launch/risk live here as the headline band. */}
      <RoleHero
        view={isMarketing ? "marketing" : "brand"}
        role={role === "admin" ? (isMarketing ? "marketing" : "brand_manager") : role}
        totalMentions={totalMentions}
        positivePct={positivePct}
        momentum={momentumHead?.value ?? null}
        bpi={bpiHead?.value ?? null}
        bpiInsufficient={bpiInsufficient}
        bpiConfidence={bpiHead?.confidence ?? null}
        bpiFlywheel={bpi?.context?.flywheel_delta ?? 0}
        launchVerdict={launchVerdict}
        launchScore={launchHead?.value ?? null}
        launchInsufficient={launchInsufficient}
        riskMentions={riskMentions}
        sentBreak={sentBreak}
        onRisk={(role === "pharmacist" || role === "admin") ? () => navigate("/adverse-events") : undefined}
      />

      {/* Role-specific intelligence panel */}
      {isMarketing ? (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-base font-semibold text-gray-900 mb-1 flex items-center gap-1.5">
            Message Resonance <InfoTip text={define("Message Resonance")} label="Message Resonance" />
          </h2>
          <p className="text-xs text-gray-400 mb-4">{keyHead?.label ?? "Which themes land with audiences — winning vs losing"}</p>
          {winning.length === 0 && losing.length === 0 ? (
            <p className="text-sm text-gray-400">Not enough classified mentions to score message resonance yet.</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-2">
              {winning.slice(0, 5).map((w: any, i: number) => (
                <div key={`w${i}`} className="flex items-center justify-between text-sm">
                  <span className="text-gray-700">✅ {String(w.topic ?? w).replace("_", " ")}</span>
                  <span className="text-green-600 font-medium">winning</span>
                </div>
              ))}
              {losing.slice(0, 5).map((l: any, i: number) => (
                <div key={`l${i}`} className="flex items-center justify-between text-sm">
                  <span className="text-gray-700">⚠ {String(l.topic ?? l).replace("_", " ")}</span>
                  <span className="text-red-500 font-medium">losing</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-6">
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-base font-semibold text-gray-900 flex items-center gap-1.5">
                BPI — Component Breakdown <InfoTip text={define("Brand Potential Index")} label="Brand Potential Index" />
              </h2>
            </div>
            <p className="text-[11px] text-slate-500 mb-2">Score above = <span className="font-medium">average of the measured signals</span>. Greyed signals ("—") have no data and are excluded — not counted as zero.</p>
            {bpiInsufficient || bpiComponents.length === 0 ? (
              <p className="text-sm text-gray-400">Insufficient data — no mentions linked to this brand in the last 365 days, so a Brand Potential Index can't be scored yet.</p>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                {bpiComponents.map((c: any) => {
                  const v = c.value == null || Number.isNaN(c.value) ? null : Math.round(c.value);
                  // Status-first: a neutral-fallback 50 or sole-brand 100 is NOT a real reading.
                  let q: { word: string; dot: string; text: string };
                  let display: string;       // what to show as the number
                  let muted = false;
                  if (c.status === "no_data") {
                    q = { word: "No data", dot: "bg-slate-600", text: "text-slate-500" };
                    display = "—"; muted = true;
                  } else if (c.status === "sole_brand") {
                    if ((v ?? 0) >= 100) {
                      q = { word: "Only brand tracked", dot: "bg-sky-500", text: "text-sky-300" };
                      display = String(v); muted = true;   // 100% but no competitors → not real dominance
                    } else {
                      q = { word: "No category peers", dot: "bg-slate-600", text: "text-slate-500" };
                      display = "—"; muted = true;
                    }
                  } else if (c.status === "no_signal" || v === 0) {
                    q = { word: "No signal", dot: "bg-slate-500", text: "text-slate-400" };
                    display = "—"; muted = true;   // excluded from the score — don't show a literal 0
                  } else if (v == null) {
                    q = { word: "No data", dot: "bg-slate-600", text: "text-slate-500" };
                    display = "—"; muted = true;
                  } else {
                    q = v >= 70
                      ? { word: c.status === "proxy" ? "Strong · proxy" : "Strong", dot: "bg-emerald-400", text: "text-emerald-300" }
                      : v >= 40
                        ? { word: c.status === "proxy" ? "Moderate · proxy" : "Moderate", dot: "bg-amber-400", text: "text-amber-300" }
                        : { word: c.status === "proxy" ? "Weak · proxy" : "Weak", dot: "bg-rose-400", text: "text-rose-300" };
                    display = String(v);
                  }
                  return (
                    <div key={c.axis} className="rounded-lg border border-white/10 bg-white/[0.04] px-4 py-3">
                      <div className="flex items-center justify-between gap-2">
                        {/* truncate only the label text — keep InfoTip outside the
                            overflow-hidden box, else its tooltip gets clipped */}
                        <span className="min-w-0 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">
                          <span className="truncate">{c.axis}</span>
                          <InfoTip text={metricDef(c.axis)} label={c.axis} />
                        </span>
                        <span className={`inline-flex shrink-0 items-center gap-1 text-[10px] font-semibold ${q.text}`}>
                          <span className={`h-1.5 w-1.5 rounded-full ${q.dot}`} />
                          {q.word}
                        </span>
                      </div>
                      <div className="mt-1.5 flex items-baseline gap-1">
                        <span className={`text-2xl font-bold tabular-nums leading-none ${muted ? "text-slate-500" : "text-white"}`}>{display}</span>
                        {display !== "—" && <span className="text-[11px] text-slate-500">/100</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="text-base font-semibold text-gray-900 mb-4 flex items-center gap-1.5">
              Launch &amp; Demand <InfoTip text={define("Demand Momentum")} label="Demand Momentum" />
            </h2>
            <div className="flex items-start gap-4">
              {(() => {
                const mv = momentumHead?.value == null || Number.isNaN(momentumHead?.value) ? null : Math.round(momentumHead.value);
                const q =
                  mv == null || mv === 0
                    ? { word: "No signal", dot: "bg-slate-500", text: "text-slate-400" }
                    : mv >= 70
                      ? { word: "Strong", dot: "bg-emerald-400", text: "text-emerald-300" }
                      : mv >= 40
                        ? { word: "Moderate", dot: "bg-amber-400", text: "text-amber-300" }
                        : { word: "Weak", dot: "bg-rose-400", text: "text-rose-300" };
                return (
                  <div className="w-36 shrink-0 rounded-lg border border-white/10 bg-white/[0.04] px-4 py-3">
                    <span className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Demand momentum</span>
                    <div className="mt-1.5 flex items-baseline gap-1">
                      <span className="text-3xl font-bold text-white tabular-nums leading-none">{mv == null ? "—" : mv}</span>
                      <span className="text-[11px] text-slate-500">/100</span>
                    </div>
                    <span className={`mt-2 inline-flex items-center gap-1 text-[10px] font-semibold ${q.text}`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${q.dot}`} />
                      {q.word}
                    </span>
                  </div>
                );
              })()}
              <div className="flex-1 min-w-0 space-y-2.5">
                <div className="flex items-center justify-between gap-2">
                  {/* The headline Launch Readiness score + verdict live ONCE, in
                      the hero card above. Here we show only the component
                      breakdown, so the same 74/100 + verdict isn't repeated. */}
                  <span className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
                    Launch readiness — breakdown
                  </span>
                  {launchInsufficient && (
                    <span className="inline-flex items-center gap-1 rounded-lg border border-white/15 bg-white/5 px-2.5 py-1 text-[11px] font-semibold text-slate-400">
                      Not scored yet
                    </span>
                  )}
                </div>
                {launchInsufficient ? (
                  <p className="text-sm text-slate-400 leading-relaxed">
                    No recent mentions in the 365-day window, so launch readiness can't be scored. Demand momentum (left) reflects the latest available signal.
                  </p>
                ) : (
                  <div className="grid grid-cols-2 gap-2">
                    {/* Sub-scores EXCLUDING BPI + Momentum (already the BPI panel /
                        Demand-momentum gauge) AND Lifecycle — its "95" is a fixed
                        stage→fit constant, not a measurement, so it's shown as a
                        stage on Brand Potential, not as a fake /100 tile here. */}
                    {(launch?.metrics ?? [])
                      .slice(1)
                      .filter((m: any) => !["BPI", "Momentum"].includes(m.label) && !String(m.label).startsWith("Lifecycle"))
                      .slice(0, 4)
                      .map((m: any, i: number) => (
                        <StatTile key={i} label={m.label} value={m.value} unit={m.unit === "%" ? "%" : ""} info={metricDef(m.label)} />
                      ))}
                  </div>
                )}
              </div>
            </div>
            {/* (Brand-risk count + Review now live once, in the hero's Brand Risk
                tile — removed here to avoid the duplicate line.) */}
          </div>
        </div>
      )}

      {summary && (
        <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100 rounded-xl p-5" style={{ order: ord.exec }}>
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={16} className="text-blue-600" />
            <h2 className="text-sm font-semibold text-blue-900">Executive Summary — what changed &amp; what to do</h2>
            <span className="text-xs text-blue-400 ml-auto">{summary.period_start} → {summary.period_end}</span>
          </div>
          <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{summary.summary}</p>
        </div>
      )}

      {/* Datatopia framework KPIs for this brand, scoped to the role */}
      {/* Demand/Buzz momentum is already the headline (Launch & Demand panel /
          Buzz Momentum card) — exclude the duplicate grid KPI so it shows once. */}
      <div style={{ order: ord.framework }}>
        <FrameworkKpiSection brandId={brandId} role={frameworkRole} excludeKeys={["mk_search_momentum"]} />
      </div>

      {/* Shared analytics: sentiment + topics */}
      <div className="grid grid-cols-2 gap-6" style={{ order: ord.charts }}>
        {sentimentPieData.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="text-base font-semibold text-gray-900 mb-4">Sentiment Breakdown</h2>
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={sentimentPieData} cx="50%" cy="50%" outerRadius={80} dataKey="value" label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}>
                  {sentimentPieData.map((entry: any, i: number) => (
                    <Cell key={i} fill={SENTIMENT_COLOURS[entry.name] ?? "#94a3b8"} />
                  ))}
                </Pie>
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}

        {topicBarData.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="text-base font-semibold text-gray-900 mb-4">{isMarketing ? "Conversation Topics" : "Topic Clusters"}</h2>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={topicBarData} layout="vertical">
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={90} />
                <Tooltip formatter={(v: any) => [`${v} mentions`]} />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {topicBarData.map((_: any, i: number) => (
                    <Cell key={i} fill={TOPIC_COLOURS[i % TOPIC_COLOURS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Live competitor intelligence (shared) */}
      <div className="bg-white rounded-xl border border-gray-200" style={{ order: ord.competitor }}>
        <div className="px-5 py-4 border-b border-gray-100">
          <h2 className="text-base font-semibold text-gray-900">Live Competitor Intelligence</h2>
          <p className="text-xs text-gray-400 mt-0.5">Search any competitor brand or drug to see what people are saying right now.</p>
        </div>
        <div className="px-5 py-4 space-y-3">
          <form
            onSubmit={(e) => { e.preventDefault(); if (competitorInput.trim().length >= 2) setCompetitorQuery(competitorInput.trim()); }}
            className="flex gap-2"
          >
            <input
              value={competitorInput}
              onChange={(e) => setCompetitorInput(e.target.value)}
              placeholder="Competitor brand or drug (e.g. Voltaren, Advil, Dafalgan)…"
              className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
            <button
              type="submit"
              disabled={competitorFetching}
              className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {competitorFetching ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
              {competitorFetching ? "Searching…" : "Analyse"}
            </button>
          </form>

          {!competitorFetching && liveCompetitor && (
            liveCompetitor.total === 0 ? (
              <p className="text-sm text-gray-400 py-3 text-center">No results for "{competitorQuery}".</p>
            ) : (
              <div>
                <div className="flex items-center gap-4 py-2 border-b border-gray-100 mb-2">
                  <div className="text-center">
                    <p className="text-2xl font-bold text-gray-900">{liveCompetitor.total}</p>
                    <p className="text-xs text-gray-400">articles (30d)</p>
                  </div>
                  <button
                    onClick={() => navigate(`/search?q=${encodeURIComponent(competitorQuery)}`)}
                    className="ml-auto text-xs text-blue-600 hover:underline flex items-center gap-1"
                  >
                    Full search <ExternalLink size={11} />
                  </button>
                </div>
                <div className="divide-y divide-gray-50 max-h-64 overflow-y-auto">
                  {(liveCompetitor.results as any[]).slice(0, 6).map((r: any, i: number) => (
                    <div key={i} className="py-2.5 flex items-start gap-2">
                      <span className={`shrink-0 text-xs px-1.5 py-0.5 rounded font-medium mt-0.5 ${r.sentiment === "positive" ? "bg-green-100 text-green-700" : r.sentiment === "negative" ? "bg-red-100 text-red-700" : "bg-gray-100 text-gray-500"}`}>
                        {r.sentiment}
                      </span>
                      <p className="text-sm text-gray-700 leading-snug line-clamp-2 flex-1">{r.text}</p>
                      {r.source_url && (
                        <a href={r.source_url} target="_blank" rel="noopener noreferrer" className="shrink-0 text-gray-300 hover:text-blue-500">
                          <ExternalLink size={12} />
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )
          )}

          {!competitorFetching && !liveCompetitor && (
            <p className="text-xs text-gray-300 text-center py-4">Enter a competitor brand above to see live public sentiment.</p>
          )}
        </div>
      </div>

      <div className="bg-gradient-to-r from-blue-600 to-indigo-600 rounded-xl p-5 flex items-center justify-between" style={{ order: ord.cta }}>
        <div>
          <h2 className="text-white font-semibold">Search brand mentions</h2>
          <p className="text-blue-100 text-sm mt-0.5">Explore what people are saying about any brand or drug across all sources.</p>
        </div>
        <button
          onClick={() => navigate("/search")}
          className="flex items-center gap-2 bg-white text-blue-700 font-medium text-sm px-4 py-2 rounded-lg hover:bg-blue-50 transition-colors shrink-0"
        >
          <Search size={15} /> Open Search
        </button>
      </div>
    </div>
  );
}
