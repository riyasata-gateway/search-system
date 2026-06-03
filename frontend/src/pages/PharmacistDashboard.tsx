import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { TrendingUp, Package, AlertCircle, Download, CheckCircle, X, Search, Loader2, ShoppingCart, AlertTriangle } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

function useDashboard() {
  return useQuery({
    queryKey: ["pharmacist-dashboard"],
    queryFn: () => apiClient.get("/pharmacist/dashboard").then((r) => r.data),
  });
}

function useRecommendations(status?: string) {
  return useQuery({
    queryKey: ["recommendations", status],
    queryFn: () =>
      apiClient
        .get("/pharmacist/recommendations", { params: status ? { status } : {} })
        .then((r) => r.data),
  });
}

const QUICK_SEARCHES = ["flu treatment", "pain relief", "antibiotic", "vitamin D", "allergy medication"];

function useLiveIntelligence(drug: string, enabled: boolean) {
  return useQuery({
    queryKey: ["pharmacist-intelligence", drug],
    queryFn: () =>
      apiClient
        .get("/search/live", { params: { q: drug, sources: "news", period: "30d" }, timeout: 25_000 })
        .then((r) => r.data),
    enabled: enabled && drug.length >= 2,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

function SignalBadge({ topic, isRisk }: { topic: string; isRisk: boolean }) {
  if (isRisk) return (
    <span className="flex items-center gap-1 text-xs text-red-600 bg-red-50 border border-red-200 px-2 py-0.5 rounded-full font-medium">
      <AlertTriangle size={10} /> Safety alert
    </span>
  );
  if (topic === "availability") return (
    <span className="text-xs text-orange-600 bg-orange-50 border border-orange-200 px-2 py-0.5 rounded-full font-medium">Shortage signal</span>
  );
  return (
    <span className="text-xs text-blue-600 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded-full font-medium">
      <span className="inline-flex items-center gap-1"><ShoppingCart size={10} /> In demand</span>
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colours: Record<string, string> = {
    pending: "bg-yellow-100 text-yellow-800",
    accepted: "bg-green-100 text-green-800",
    dismissed: "bg-gray-100 text-gray-600",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${colours[status] ?? "bg-gray-100 text-gray-600"}`}>
      {status}
    </span>
  );
}

function ActionTypeBadge({ type }: { type: string }) {
  const colours: Record<string, string> = {
    add: "bg-blue-100 text-blue-800",
    reorder: "bg-orange-100 text-orange-800",
    monitor: "bg-purple-100 text-purple-800",
    ignore: "bg-gray-100 text-gray-500",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${colours[type] ?? "bg-gray-100"}`}>
      {type}
    </span>
  );
}

export default function PharmacistDashboard() {
  const { data: dashboard, isLoading } = useDashboard();
  const { data: recommendations } = useRecommendations("pending");
  const queryClient = useQueryClient();
  const [drugInput, setDrugInput] = useState("");
  const [drugQuery, setDrugQuery] = useState("");

  const updateAction = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      apiClient.put(`/pharmacist/recommendations/${id}/action`, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recommendations"] });
      queryClient.invalidateQueries({ queryKey: ["pharmacist-dashboard"] });
    },
  });

  const handleExport = async (fmt: "csv" | "xlsx") => {
    const res = await apiClient.get(`/pharmacist/recommendations/export`, {
      params: { fmt },
      responseType: "blob",
    });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `recommendations.${fmt}`;
    a.click();
  };

  const { data: intel, isFetching: intelFetching } = useLiveIntelligence(drugQuery, drugQuery.length >= 2);

  if (isLoading) return <div className="text-gray-500 text-sm">Loading dashboard…</div>;

  const trendData = (dashboard?.trending_categories ?? []).slice(0, 8).map((t: any) => ({
    name: t.category_name ?? `Category ${t.entity_id}`,
    score: parseFloat(t.score).toFixed(1),
    change: t.relative_change ? parseFloat(t.relative_change).toFixed(0) : 0,
  }));

  // Pharmacist-facing copy built from structured fields — never shows the raw
  // category id, and falls back to the stored reason only if names are missing.
  const recLine = (rec: any): string => {
    const cat = rec.category_name;
    const prod = rec.product_name;
    if (prod && cat) {
      return rec.action === "reorder"
        ? `${prod} (${cat}) is trending — reorder soon to avoid a stockout.`
        : `${cat} is trending. You don't stock ${prod} — consider adding it.`;
    }
    return rec.reason;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{dashboard?.pharmacy_name ?? "My Pharmacy"}</h1>
          <p className="text-sm text-gray-500">{dashboard?.country} · Pharmacist Intelligence</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => handleExport("csv")}
            className="flex items-center gap-1.5 text-sm px-3 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            <Download size={15} /> Export CSV
          </button>
          <button
            onClick={() => handleExport("xlsx")}
            className="flex items-center gap-1.5 text-sm px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            <Download size={15} /> Export XLSX
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Pending Recommendations", value: dashboard?.pending_recommendations ?? 0, icon: Package, colour: "text-blue-600" },
          { label: "Trending Categories", value: dashboard?.trending_categories?.length ?? 0, icon: TrendingUp, colour: "text-green-600" },
          { label: "Alerts", value: "-", icon: AlertCircle, colour: "text-orange-500" },
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

      {trendData.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-base font-semibold text-gray-900 mb-4">Trending Categories (30d)</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={trendData}>
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="score" radius={[4, 4, 0, 0]}>
                {trendData.map((_: any, i: number) => (
                  <Cell key={i} fill={i % 2 === 0 ? "#3b82f6" : "#93c5fd"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-900">Recommendations</h2>
          <span className="text-xs text-gray-400">{recommendations?.length ?? 0} pending</span>
        </div>
        <div className="divide-y divide-gray-50">
          {(recommendations ?? []).length === 0 && (
            <p className="text-sm text-gray-400 px-5 py-8 text-center">No pending recommendations.</p>
          )}
          {(recommendations ?? []).map((rec: any) => (
            <div key={rec.id} className="px-5 py-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <ActionTypeBadge type={rec.action} />
                    <StatusBadge status={rec.status} />
                    <span className="text-xs text-gray-400">
                      Confidence: {rec.confidence_score ? `${(rec.confidence_score * 100).toFixed(0)}%` : "—"}
                    </span>
                  </div>
                  <p className="text-sm text-gray-700 leading-relaxed">{recLine(rec)}</p>
                  {rec.source_refs?.length > 0 && (
                    <div className="flex gap-1 mt-1.5 flex-wrap">
                      {rec.source_refs.map((ref: string, i: number) => (
                        <span key={i} className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded">{ref}</span>
                      ))}
                    </div>
                  )}
                </div>
                {rec.status === "pending" && (
                  <div className="flex gap-1.5 shrink-0">
                    <button
                      onClick={() => updateAction.mutate({ id: rec.id, status: "accepted" })}
                      className="p-1.5 rounded-lg hover:bg-green-50 text-gray-400 hover:text-green-600"
                      title="Accept"
                    >
                      <CheckCircle size={16} />
                    </button>
                    <button
                      onClick={() => updateAction.mutate({ id: rec.id, status: "dismissed" })}
                      className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-500"
                      title="Dismiss"
                    >
                      <X size={16} />
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Live Market Intelligence ─────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-gray-200">
        <div className="px-5 py-4 border-b border-gray-100">
          <h2 className="text-base font-semibold text-gray-900">Live Market Intelligence</h2>
          <p className="text-xs text-gray-400 mt-0.5">Search any drug or category to see real-time demand signals and safety alerts from the internet (last 30 days). Use this to decide what to stock or monitor.</p>
        </div>
        <div className="px-5 py-4 space-y-3">
          <form
            onSubmit={(e) => { e.preventDefault(); if (drugInput.trim().length >= 2) setDrugQuery(drugInput.trim()); }}
            className="flex gap-2"
          >
            <input
              value={drugInput}
              onChange={(e) => setDrugInput(e.target.value)}
              placeholder="e.g. ibuprofen, flu treatment, vitamin D…"
              className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
            <button
              type="submit"
              className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
              disabled={intelFetching}
            >
              {intelFetching ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
              {intelFetching ? "Searching…" : "Check"}
            </button>
          </form>
          <div className="flex gap-2 flex-wrap">
            {QUICK_SEARCHES.map((qs) => (
              <button
                key={qs}
                type="button"
                onClick={() => { setDrugInput(qs); setDrugQuery(qs); }}
                className="text-xs px-2.5 py-1 rounded-full border border-gray-200 text-gray-500 hover:border-blue-400 hover:text-blue-600 transition-colors bg-gray-50"
              >
                {qs}
              </button>
            ))}
          </div>

          {intelFetching && (
            <div className="flex items-center gap-2 py-4 text-sm text-blue-600">
              <Loader2 size={16} className="animate-spin" /> Fetching live signals…
            </div>
          )}

          {!intelFetching && intel && (
            <>
              {intel.total === 0 ? (
                <p className="text-sm text-gray-400 py-4 text-center">No recent articles found for "{drugQuery}". Try a broader term.</p>
              ) : (
                <div className="space-y-1">
                  <div className="flex items-center justify-between py-1">
                    <span className="text-xs font-semibold text-gray-600">
                      {intel.total} articles in last 30 days for <span className="text-blue-600">"{drugQuery}"</span>
                    </span>
                    {intel.total >= 10 && (
                      <span className="text-xs bg-green-100 text-green-700 border border-green-200 px-2 py-0.5 rounded-full font-medium">
                        ✓ Stock recommended
                      </span>
                    )}
                    {intel.results?.filter((r: any) => r.is_risk).length > 0 && (
                      <span className="text-xs bg-red-100 text-red-700 border border-red-200 px-2 py-0.5 rounded-full font-medium ml-2">
                        ⚠ {intel.results.filter((r: any) => r.is_risk).length} safety signals
                      </span>
                    )}
                  </div>
                  <div className="divide-y divide-gray-50 max-h-80 overflow-y-auto">
                    {(intel.results as any[]).slice(0, 8).map((r: any, i: number) => (
                      <div key={i} className="py-3 flex items-start gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5 mb-1 flex-wrap">
                            <SignalBadge topic={r.topic} isRisk={r.is_risk} />
                            <span className="text-xs text-gray-400">{r.country} · {r.language}</span>
                            {r.published_at && (
                              <span className="text-xs text-gray-300">{new Date(r.published_at).toLocaleDateString()}</span>
                            )}
                          </div>
                          <p className="text-sm text-gray-700 leading-snug line-clamp-2">{r.text}</p>
                        </div>
                        {r.source_url && (
                          <a href={r.source_url} target="_blank" rel="noopener noreferrer" className="shrink-0 text-gray-300 hover:text-blue-500 pt-1">
                            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {!intelFetching && !intel && !drugQuery && (
            <p className="text-xs text-gray-300 text-center py-6">Enter a drug or category above to check real-time demand and safety signals.</p>
          )}
        </div>
      </div>
    </div>
  );
}
