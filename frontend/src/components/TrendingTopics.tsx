import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { Hash, ArrowUp, ArrowDown, Minus } from "lucide-react";

/** B9 — Trending topics: a sized topic-cloud with rising/falling direction. */

type Topic = { topic: string; total: number; recent: number; prior: number; direction: string };

const DIR = {
  rising: { icon: ArrowUp, cls: "text-emerald-600" },
  falling: { icon: ArrowDown, cls: "text-red-500" },
  flat: { icon: Minus, cls: "text-slate-400" },
} as const;

export default function TrendingTopics({ brandId }: { brandId: number | null }) {
  const { data, isLoading } = useQuery<{ topics: Topic[] }>({
    queryKey: ["trending-topics", brandId],
    queryFn: () => apiClient.get(`/intelligence/trending-topics/${brandId}`).then((r) => r.data),
    enabled: brandId != null,
  });
  if (brandId == null) return null;

  const topics = data?.topics ?? [];
  const max = Math.max(1, ...topics.map((t) => t.total));
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1.5 mb-1">
        <Hash size={14} /> Trending topics
      </h3>
      <p className="text-[11px] text-slate-400 mb-3">What people discuss, sized by volume · arrow = last 90d vs prior.</p>
      {isLoading ? (
        <p className="text-xs text-slate-400 py-6 text-center">Loading…</p>
      ) : topics.length === 0 ? (
        <p className="text-xs text-slate-400 py-6 text-center">No themed discussion classified for this brand yet.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {topics.map((t) => {
            const scale = 0.8 + (t.total / max) * 0.9; // 0.8–1.7rem-ish
            const d = DIR[(t.direction as keyof typeof DIR)] ?? DIR.flat;
            const Icon = d.icon;
            return (
              <span key={t.topic}
                className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 capitalize"
                style={{ fontSize: `${scale * 0.8}rem` }}
                title={`${t.total} mentions · ${t.recent} recent vs ${t.prior} prior`}>
                {t.topic.replace(/_/g, " ")}
                <Icon size={12} className={d.cls} />
                <span className="text-[10px] text-slate-400 tabular-nums">{t.total}</span>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
