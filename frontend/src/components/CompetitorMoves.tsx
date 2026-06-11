import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { Swords, TrendingUp } from "lucide-react";

/** B10 — Competitor-movement detection: peers with rising demand momentum. */

type Move = { name: string; momentum: number; velocity: number; current: number; rising: boolean };

export default function CompetitorMoves({ brandId }: { brandId: number | null }) {
  const { data, isLoading } = useQuery<{ moves: Move[] }>({
    queryKey: ["competitor-moves", brandId],
    queryFn: () => apiClient.get(`/intelligence/competitor-moves/${brandId}`).then((r) => r.data),
    enabled: brandId != null,
  });
  if (brandId == null) return null;

  const moves = data?.moves ?? [];
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1.5 mb-1">
        <Swords size={14} /> Competitor movement
      </h3>
      <p className="text-[11px] text-slate-400 mb-3">Demand momentum across your competing set — a rising peer may be making a move.</p>
      {isLoading ? (
        <p className="text-xs text-slate-400 py-6 text-center">Loading…</p>
      ) : moves.length === 0 ? (
        <p className="text-xs text-slate-400 py-6 text-center">No competitor with enough recent signal to score a move.</p>
      ) : (
        <ul className="space-y-1.5">
          {moves.map((m) => (
            <li key={m.name} className="flex items-center gap-3">
              <span className="flex-1 min-w-0 text-sm text-slate-700 truncate">{m.name}</span>
              <div className="w-28 h-1.5 rounded-full bg-slate-100 overflow-hidden shrink-0">
                <span className="block h-full rounded-full"
                  style={{ width: `${Math.min(100, m.momentum)}%`, backgroundColor: m.rising ? "#10b981" : "#94a3b8" }} />
              </div>
              <span className="w-10 text-right text-xs tabular-nums text-slate-500 shrink-0">{m.momentum}</span>
              {m.rising && (
                <span className="shrink-0 inline-flex items-center gap-0.5 text-[10px] font-semibold text-emerald-600">
                  <TrendingUp size={11} /> rising
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
