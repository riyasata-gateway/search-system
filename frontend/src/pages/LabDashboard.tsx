import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import {
  TrendingUp, MessageSquare, AlertTriangle, Search, Loader2, ExternalLink,
  Megaphone, Briefcase, Activity, Target, Rocket, Radio,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

const SENTIMENT_COLOURS: Record<string, string> = {
  positive: "#22c55e",
  neutral: "#94a3b8",
  negative: "#ef4444",
};

const TOPIC_COLOURS = ["#3b82f6", "#8b5cf6", "#f59e0b", "#10b981", "#f43f5e", "#06b6d4", "#84cc16"];

const SOURCE_COLOURS: Record<string, string> = {
  news: "#3b82f6",
  rss: "#8b5cf6",
  forum: "#f59e0b",
  google_trends: "#10b981",
  reddit: "#f43f5e",
  youtube: "#ef4444",
  licensed_api: "#06b6d4",
};

// ── data hooks (all brand-scoped via ?brand_id) ──────────────────────────────
function useMyBrands() {
  return useQuery({
    queryKey: ["lab-my-brands"],
    queryFn: () => apiClient.get("/lab/my-brands").then((r) => r.data),
  });
}

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
function KpiCard({ label, value, icon: Icon, colour, suffix }: any) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-gray-500">{label}</span>
        <Icon size={18} className={colour} />
      </div>
      <p className="text-3xl font-bold text-gray-900">
        {value}
        {suffix && <span className="text-base font-medium text-gray-400 ml-1">{suffix}</span>}
      </p>
    </div>
  );
}

function GaugeBar({ label, value, unit }: { label: string; value: number | null; unit?: string }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(100, value));
  const colour = pct >= 66 ? "#22c55e" : pct >= 40 ? "#f59e0b" : "#ef4444";
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-gray-600">{label}</span>
        <span className="font-semibold text-gray-900 tabular-nums">{fmt(value)}{unit ? ` ${unit}` : ""}</span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: colour }} />
      </div>
    </div>
  );
}

export default function LabDashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const role = user?.role ?? "brand_manager";

  // marketing → reach/resonance view; brand_manager → market/risk view; admin → toggle.
  const [adminView, setAdminView] = useState<"marketing" | "brand">("brand");
  const view = role === "marketing" ? "marketing" : role === "brand_manager" ? "brand" : adminView;
  const isMarketing = view === "marketing";

  const { data: myBrands } = useMyBrands();
  const [brandId, setBrandId] = useState<number | null>(null);
  useEffect(() => {
    if (brandId == null && myBrands?.length) {
      const withData = myBrands.find((b: any) => b.has_data);
      setBrandId((withData ?? myBrands[0]).id);
    }
  }, [myBrands, brandId]);

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

  const activeBrand = (myBrands ?? []).find((b: any) => b.id === brandId);

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
  const sourceBreakdown: Record<string, number> = dashboard?.source_breakdown ?? {};
  const sourceGroups = Object.entries(sourceBreakdown)
    .map(([source_type, total]) => ({ source_type, total: Number(total) }))
    .sort((a, b) => b.total - a.total);
  const totalAcrossSources = sourceGroups.reduce((sum, g) => sum + g.total, 0) || 1;

  const bpiHead = headline(bpi);
  const launchHead = headline(launch);
  const momentumHead = headline(momentum);
  const keyHead = headline(keyMsg);
  const winning = keyMsg?.context?.winning ?? [];
  const losing = keyMsg?.context?.losing ?? [];

  if (isLoading && brandId != null) return <div className="text-gray-500 text-sm">Loading dashboard…</div>;

  return (
    <div className="space-y-6">
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
          <select
            value={brandId ?? ""}
            onChange={(e) => setBrandId(Number(e.target.value))}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
            {(myBrands ?? []).map((b: any) => (
              <option key={b.id} value={b.id}>
                {b.name}{b.has_data ? "" : " (no data yet)"}
              </option>
            ))}
          </select>
        </div>
      </div>

      {activeBrand && !activeBrand.has_data && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-2.5 text-sm text-amber-800">
          No mentions linked to <strong>{activeBrand.name}</strong> yet — this brand will populate as the corpus grows.
        </div>
      )}

      {/* Role-specific KPI row */}
      <div className="grid grid-cols-3 gap-4">
        {isMarketing ? (
          <>
            <KpiCard label="Total Reach (mentions)" value={totalMentions} icon={Radio} colour="text-amber-500" />
            <KpiCard label="Positive Sentiment" value={positivePct} suffix="%" icon={MessageSquare} colour="text-green-600" />
            <KpiCard label="Buzz Momentum" value={fmt(momentumHead?.value)} suffix="/100" icon={Activity} colour="text-blue-600" />
          </>
        ) : (
          <>
            <KpiCard label="Brand Potential Index" value={fmt(bpiHead?.value)} suffix="/100" icon={Target} colour="text-purple-600" />
            <KpiCard label="Launch Readiness" value={fmt(launchHead?.value)} suffix="/100" icon={Rocket} colour="text-indigo-600" />
            <KpiCard label="Risk Mentions" value={riskMentions} icon={AlertTriangle} colour="text-orange-500" />
          </>
        )}
      </div>

      {/* Role-specific intelligence panel */}
      {isMarketing ? (
        <div className="grid grid-cols-2 gap-6">
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="text-base font-semibold text-gray-900 mb-1">Message Resonance</h2>
            <p className="text-xs text-gray-400 mb-4">{keyHead?.label ?? "Which topics land with audiences"}</p>
            {winning.length === 0 && losing.length === 0 ? (
              <p className="text-sm text-gray-400">Not enough classified mentions to score message resonance yet.</p>
            ) : (
              <div className="space-y-3">
                {winning.slice(0, 4).map((w: any, i: number) => (
                  <div key={`w${i}`} className="flex items-center justify-between text-sm">
                    <span className="text-gray-700">✅ {String(w.topic ?? w).replace("_", " ")}</span>
                    <span className="text-green-600 font-medium">winning</span>
                  </div>
                ))}
                {losing.slice(0, 4).map((l: any, i: number) => (
                  <div key={`l${i}`} className="flex items-center justify-between text-sm">
                    <span className="text-gray-700">⚠ {String(l.topic ?? l).replace("_", " ")}</span>
                    <span className="text-red-500 font-medium">losing</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="text-base font-semibold text-gray-900 mb-4">Buzz & Reach</h2>
            <div className="space-y-3">
              <GaugeBar label="Buzz momentum" value={momentumHead?.value ?? null} unit="/100" />
              <GaugeBar label="Positive sentiment" value={positivePct} unit="%" />
              <div className="pt-2 text-xs text-gray-400">
                Reach across {sourceGroups.length} channels · {totalMentions} mentions analysed
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-6">
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="text-base font-semibold text-gray-900 mb-4">Brand Potential Index</h2>
            <div className="space-y-3">
              {(bpi?.metrics ?? []).map((m: any, i: number) => (
                <GaugeBar key={i} label={m.label} value={m.value} unit={m.unit === "%" ? "%" : ""} />
              ))}
              {!bpi && <p className="text-sm text-gray-400">No BPI computed yet.</p>}
            </div>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="text-base font-semibold text-gray-900 mb-4">Launch & Demand</h2>
            <div className="space-y-3">
              <GaugeBar label={launchHead?.label ?? "Launch readiness"} value={launchHead?.value ?? null} unit="/100" />
              <GaugeBar label="Demand momentum" value={momentumHead?.value ?? null} unit="/100" />
              <div className="pt-1 flex items-center justify-between text-sm">
                <span className="text-gray-600">Open brand-risk / adverse-event queue</span>
                <button onClick={() => navigate("/adverse-events")} className="text-purple-600 hover:underline text-xs flex items-center gap-1">
                  Review <ExternalLink size={11} />
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {summary && (
        <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={16} className="text-blue-600" />
            <h2 className="text-sm font-semibold text-blue-900">Weekly Executive Summary</h2>
            <span className="text-xs text-blue-400 ml-auto">{summary.period_start} → {summary.period_end}</span>
          </div>
          <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{summary.summary}</p>
        </div>
      )}

      {/* Shared analytics: sentiment + topics */}
      <div className="grid grid-cols-2 gap-6">
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

      {/* Source / channel breakdown */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="text-base font-semibold text-gray-900 mb-4">{isMarketing ? "Channel Mix" : "Source Breakdown"}</h2>
        {sourceGroups.length > 0 ? (
          <div className="space-y-3">
            {sourceGroups.map((g) => {
              const pct = (g.total / totalAcrossSources) * 100;
              const colour = SOURCE_COLOURS[g.source_type] ?? "#6366f1";
              return (
                <div key={g.source_type} className="border border-gray-100 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-sm font-medium text-gray-800 capitalize flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full" style={{ background: colour }} />
                      {g.source_type.replace("_", " ")}
                    </span>
                    <span className="text-xs text-gray-500 tabular-nums">
                      <span className="font-semibold text-gray-700">{g.total}</span> · {pct.toFixed(0)}%
                    </span>
                  </div>
                  <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: colour }} />
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-gray-400">No source data for this brand yet.</p>
        )}
      </div>

      {/* Live competitor intelligence (shared) */}
      <div className="bg-white rounded-xl border border-gray-200">
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

      <div className="bg-gradient-to-r from-blue-600 to-indigo-600 rounded-xl p-5 flex items-center justify-between">
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
