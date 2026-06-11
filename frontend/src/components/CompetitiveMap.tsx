import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer, ScatterChart, Scatter, XAxis, YAxis, ZAxis,
  Tooltip, ReferenceLine, Cell,
} from "recharts";
import { apiClient } from "../api/client";
import { Map as MapIcon } from "lucide-react";

/** B11 — Brand Competitive Map. Positions the brand vs its competing-set peers
 *  on reach (awareness) × resonance (market fit); bubble = mention volume. */

type Node = {
  id: number; name: string; bpi: number | null;
  awareness: number; adoption: number; sentiment: number; market_fit: number;
  mentions: number; is_self: boolean; insufficient: boolean;
};
type MapData = { brand: string; frame: string; peer_count: number; nodes: Node[] };

function Dot(props: any) {
  const { cx, cy, payload } = props;
  if (cx == null || cy == null) return null;
  const self = payload.is_self;
  const r = Math.max(6, Math.min(22, Math.sqrt(payload.mentions || 1) / 6));
  return (
    <g>
      <circle cx={cx} cy={cy} r={r} fill={self ? "#6366f1" : "#94a3b8"} fillOpacity={self ? 0.85 : 0.45}
        stroke={self ? "#4338ca" : "#64748b"} strokeWidth={self ? 2 : 1} />
      <text x={cx} y={cy - r - 4} textAnchor="middle" fontSize={10}
        fill={self ? "#4338ca" : "#64748b"} fontWeight={self ? 700 : 500}>{payload.name}</text>
    </g>
  );
}

export default function CompetitiveMap({ brandId }: { brandId: number | null }) {
  const { data, isLoading } = useQuery<MapData>({
    queryKey: ["competitive-map", brandId],
    queryFn: () => apiClient.get(`/intelligence/competitive-map/${brandId}`).then((r) => r.data),
    enabled: brandId != null,
  });
  if (brandId == null) return null;

  const nodes = (data?.nodes ?? []).filter((n) => !n.insufficient);
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1.5 mb-1">
        <MapIcon size={14} /> Competitive map
        {data?.frame && <span className="font-normal normal-case text-slate-400">· vs {data.frame} ({data.peer_count})</span>}
      </h3>
      <p className="text-[11px] text-slate-400 mb-2">Reach (market presence) × resonance (category fit). Bubble = mention volume; your brand in indigo.</p>
      {isLoading ? (
        <p className="text-xs text-slate-400 py-10 text-center">Loading map…</p>
      ) : nodes.length < 2 ? (
        <p className="text-xs text-slate-400 py-10 text-center">Not enough scored peers to map this brand's competitive set.</p>
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <ScatterChart margin={{ top: 20, right: 20, bottom: 28, left: 8 }}>
            <ReferenceLine x={50} stroke="#e2e8f0" strokeDasharray="3 3" />
            <ReferenceLine y={50} stroke="#e2e8f0" strokeDasharray="3 3" />
            <XAxis type="number" dataKey="awareness" name="Reach" domain={[0, 100]}
              tick={{ fontSize: 10, fill: "#94a3b8" }}
              label={{ value: "Reach / market presence →", position: "bottom", fontSize: 10, fill: "#94a3b8" }} />
            <YAxis type="number" dataKey="market_fit" name="Resonance" domain={[0, 100]}
              tick={{ fontSize: 10, fill: "#94a3b8" }}
              label={{ value: "Resonance / fit →", angle: -90, position: "insideLeft", fontSize: 10, fill: "#94a3b8" }} />
            <ZAxis type="number" dataKey="mentions" range={[60, 400]} name="Mentions" />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }}
              formatter={(v: number, k: string) => [Math.round(v), k]}
              labelFormatter={() => ""}
              content={({ payload }) => {
                const p = payload?.[0]?.payload as Node | undefined;
                if (!p) return null;
                return (
                  <div className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-xs shadow-soft">
                    <p className="font-semibold text-slate-800">{p.name}{p.is_self ? " (you)" : ""}</p>
                    <p className="text-slate-500">BPI {p.bpi ?? "—"} · reach {p.awareness} · fit {p.market_fit}</p>
                    <p className="text-slate-500">sentiment {p.sentiment}% · {p.mentions.toLocaleString()} mentions</p>
                  </div>
                );
              }}
            />
            <Scatter data={nodes} shape={<Dot />}>
              {nodes.map((n) => <Cell key={n.id} />)}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
