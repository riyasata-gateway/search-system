import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Legend,
} from "recharts";
import { apiClient } from "../api/client";
import { Newspaper } from "lucide-react";

/** B16 — Earned-media / press analysis lens: monthly news volume + sentiment. */

type Point = { month: string; articles: number; positive: number; negative: number; neutral: number };
type PressData = { total_articles: number; pos_pct: number | null; timeline: Point[] };

export default function PressLens({ brandId }: { brandId: number | null }) {
  const { data, isLoading } = useQuery<PressData>({
    queryKey: ["press-timeline", brandId],
    queryFn: () => apiClient.get(`/intelligence/press-timeline/${brandId}`).then((r) => r.data),
    enabled: brandId != null,
  });
  if (brandId == null) return null;

  const timeline = data?.timeline ?? [];
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className="flex items-center justify-between gap-2 mb-1 flex-wrap">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
          <Newspaper size={14} /> Press coverage
        </h3>
        {data && data.total_articles > 0 && (
          <span className="text-[11px] text-slate-400 tabular-nums">
            {data.total_articles} articles{data.pos_pct != null ? ` · ${data.pos_pct}% positive` : ""}
          </span>
        )}
      </div>
      <p className="text-[11px] text-slate-400 mb-2">Earned-media volume &amp; sentiment over time (brand-linked news).</p>
      {isLoading ? (
        <p className="text-xs text-slate-400 py-10 text-center">Loading press…</p>
      ) : timeline.length === 0 ? (
        <p className="text-xs text-slate-400 py-10 text-center">No brand-linked press coverage for this brand yet.</p>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={timeline} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
            <XAxis dataKey="month" tick={{ fontSize: 9, fill: "#94a3b8" }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10, fill: "#94a3b8" }} allowDecimals={false} />
            <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="positive" stackId="s" fill="#10b981" name="positive" />
            <Bar dataKey="neutral" stackId="s" fill="#cbd5e1" name="neutral" />
            <Bar dataKey="negative" stackId="s" fill="#ef4444" name="negative" />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
