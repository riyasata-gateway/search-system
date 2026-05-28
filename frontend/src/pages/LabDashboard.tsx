import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { TrendingUp, MessageSquare, AlertTriangle, Search, Loader2, ExternalLink } from "lucide-react";
import { useNavigate } from "react-router-dom";

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

function extractDomain(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

function useDashboard() {
  return useQuery({
    queryKey: ["lab-dashboard"],
    queryFn: () => apiClient.get("/lab/dashboard").then((r) => r.data),
  });
}

function useWeeklySummary() {
  return useQuery({
    queryKey: ["weekly-summary"],
    queryFn: () => apiClient.get("/lab/weekly-summary").then((r) => r.data),
    staleTime: 3_600_000,
  });
}

function useSentimentBreakdown() {
  return useQuery({
    queryKey: ["sentiment-breakdown"],
    queryFn: () => apiClient.get("/lab/sentiment-breakdown").then((r) => r.data),
  });
}

function useTopicClusters() {
  return useQuery({
    queryKey: ["topic-clusters"],
    queryFn: () => apiClient.get("/lab/topic-clusters").then((r) => r.data),
  });
}

function useCompetitorComparison(groupId: number | null) {
  return useQuery({
    queryKey: ["competitor-comparison", groupId],
    queryFn: () =>
      apiClient.get("/lab/competitor-comparison", { params: { competitor_group_id: groupId } }).then((r) => r.data),
    enabled: !!groupId,
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

export default function LabDashboard() {
  const navigate = useNavigate();
  const [competitorInput, setCompetitorInput] = useState("");
  const [competitorQuery, setCompetitorQuery] = useState("");
  const { data: dashboard, isLoading } = useDashboard();
  const { data: summary } = useWeeklySummary();
  const { data: sentiment } = useSentimentBreakdown();
  const { data: topics } = useTopicClusters();
  const { data: liveCompetitor, isFetching: competitorFetching } = useLiveCompetitor(competitorQuery, competitorQuery.length >= 2);

  if (isLoading) return <div className="text-gray-500 text-sm">Loading lab dashboard…</div>;

  const sentimentPieData = (sentiment ?? []).map((s: any) => ({
    name: s.topic,
    value: s.count,
  }));

  const topicBarData = (topics ?? []).slice(0, 8).map((t: any) => ({
    name: t.topic?.replace("_", " "),
    count: t.count,
    pct: t.percent,
  }));

  const liveResults = (liveCompetitor?.results ?? []) as any[];
  const liveActive = !!liveCompetitor;
  const liveRiskCount = liveResults.filter((r: any) => r.is_risk).length;
  const liveSourceBreakdown = liveResults.reduce<Record<string, number>>((acc, r: any) => {
    if (r.source_type) acc[r.source_type] = (acc[r.source_type] ?? 0) + 1;
    return acc;
  }, {});

  const totalMentions = liveActive ? (liveCompetitor.total ?? 0) : (dashboard?.total_mentions ?? 0);
  const riskMentions = liveActive ? liveRiskCount : (dashboard?.risk_alert_count ?? 0);
  const sourceBreakdown: Record<string, number> = liveActive
    ? liveSourceBreakdown
    : (dashboard?.source_breakdown ?? {});

  const sourceGroups = liveActive
    ? Object.entries(
        liveResults.reduce<Record<string, any[]>>((acc, r: any) => {
          if (!r.source_type) return acc;
          (acc[r.source_type] ||= []).push(r);
          return acc;
        }, {})
      ).map(([source_type, items]) => {
        const domainCounts = items.reduce<Record<string, number>>((acc, r: any) => {
          const d = extractDomain(r.source_url);
          if (d) acc[d] = (acc[d] ?? 0) + 1;
          return acc;
        }, {});
        const domains = Object.entries(domainCounts)
          .sort((a, b) => b[1] - a[1])
          .map(([domain, count]) => ({ domain, count }));
        return { source_type, total: items.length, domains };
      })
    : Object.entries(sourceBreakdown).map(([source_type, total]) => ({
        source_type,
        total: Number(total),
        domains: [] as { domain: string; count: number }[],
      }));
  sourceGroups.sort((a, b) => b.total - a.total);
  const totalAcrossSources = sourceGroups.reduce((sum, g) => sum + g.total, 0) || 1;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Lab / Brand Intelligence</h1>
        <p className="text-sm text-gray-500">What are people saying about your brand?</p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Total Mentions", value: totalMentions, icon: MessageSquare, colour: "text-blue-600" },
          { label: "Risk Mentions", value: riskMentions, icon: AlertTriangle, colour: "text-orange-500" },
          { label: "Period", value: dashboard?.period ?? "30d", icon: TrendingUp, colour: "text-green-600" },
        ].map(({ label, value, icon: Icon, colour }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm text-gray-500">{label}</span>
              <Icon size={18} className={colour} />
            </div>
            <p className="text-3xl font-bold text-gray-900">{value}</p>
          </div>
        ))}
      </div>

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
            <h2 className="text-base font-semibold text-gray-900 mb-4">Topic Clusters</h2>
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

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex items-baseline justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-900">Source Breakdown</h2>
          {liveActive && (
            <span className="text-xs text-gray-400">
              {sourceGroups.reduce((s, g) => s + g.domains.length, 0)} unique domains across {sourceGroups.length} channels
            </span>
          )}
        </div>
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
                      <span className="font-semibold text-gray-700">{g.total}</span> mention{g.total === 1 ? "" : "s"} · {pct.toFixed(0)}%
                    </span>
                  </div>
                  <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden mb-2">
                    <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: colour }} />
                  </div>
                  {g.domains.length > 0 ? (
                    <div className="flex gap-1.5 flex-wrap">
                      {g.domains.slice(0, 6).map((d) => (
                        <a
                          key={d.domain}
                          href={`https://${d.domain}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="group flex items-center gap-1.5 text-xs px-2 py-1 bg-gray-50 hover:bg-blue-50 hover:border-blue-200 border border-gray-200 rounded transition-colors"
                          title={`${d.count} mention${d.count === 1 ? "" : "s"} from ${d.domain}`}
                        >
                          <img
                            src={`https://www.google.com/s2/favicons?domain=${d.domain}&sz=16`}
                            alt=""
                            className="w-3.5 h-3.5"
                            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                          />
                          <span className="text-gray-700 group-hover:text-blue-700">{d.domain}</span>
                          <span className="text-gray-400 tabular-nums">·{d.count}</span>
                        </a>
                      ))}
                      {g.domains.length > 6 && (
                        <span className="text-xs px-2 py-1 text-gray-400">+{g.domains.length - 6} more</span>
                      )}
                    </div>
                  ) : (
                    !liveActive && (
                      <p className="text-xs text-gray-300 italic">Run a competitor search above to see actual sites.</p>
                    )
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-gray-400">No source data yet — search a competitor brand below to populate.</p>
        )}
      </div>

      <div className="bg-white rounded-xl border border-gray-200">
        <div className="px-5 py-4 border-b border-gray-100">
          <h2 className="text-base font-semibold text-gray-900">Live Competitor Intelligence</h2>
          <p className="text-xs text-gray-400 mt-0.5">Search any competitor brand or drug to see what people are saying about it right now — sentiment, topics, risk signals.</p>
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

          {competitorFetching && (
            <div className="flex items-center gap-2 py-3 text-sm text-blue-600">
              <Loader2 size={16} className="animate-spin" /> Fetching live competitor data…
            </div>
          )}

          {!competitorFetching && liveCompetitor && (
            <>
              {liveCompetitor.total === 0 ? (
                <p className="text-sm text-gray-400 py-3 text-center">No results for "{competitorQuery}".</p>
              ) : (
                <div>
                  <div className="flex items-center gap-4 py-2 border-b border-gray-100 mb-2">
                    <div className="text-center">
                      <p className="text-2xl font-bold text-gray-900">{liveCompetitor.total}</p>
                      <p className="text-xs text-gray-400">articles (30d)</p>
                    </div>
                    <div className="flex gap-3">
                      {["positive","neutral","negative"].map((s) => {
                        const cnt = (liveCompetitor.results as any[]).filter((r: any) => r.sentiment === s).length;
                        const pct = liveCompetitor.total ? Math.round((cnt / liveCompetitor.total) * 100) : 0;
                        const col = s === "positive" ? "text-green-600" : s === "negative" ? "text-red-500" : "text-gray-500";
                        return cnt > 0 ? (
                          <div key={s} className="text-center">
                            <p className={`text-lg font-bold ${col}`}>{pct}%</p>
                            <p className="text-xs text-gray-400 capitalize">{s}</p>
                          </div>
                        ) : null;
                      })}
                      {(liveCompetitor.results as any[]).filter((r: any) => r.is_risk).length > 0 && (
                        <div className="text-center">
                          <p className="text-lg font-bold text-red-600">{(liveCompetitor.results as any[]).filter((r: any) => r.is_risk).length}</p>
                          <p className="text-xs text-gray-400">risk flags</p>
                        </div>
                      )}
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
              )}
            </>
          )}

          {!competitorFetching && !liveCompetitor && !competitorQuery && (
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
