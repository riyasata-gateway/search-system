import { ResponsiveContainer, RadialBarChart, RadialBar, PolarAngleAxis } from "recharts";

/**
 * A 0–100 radial score gauge — the house style for any composite score
 * (Brand Potential, Launch Readiness, Momentum, Sentiment …). Replaces the old
 * flat horizontal bars: a dial reads as "how far toward great" at a glance and
 * colour-codes the verdict (red < 40, amber < 70, green ≥ 70).
 */
function scoreColour(v: number) {
  if (v >= 70) return "#10b981";
  if (v >= 40) return "#f59e0b";
  return "#ef4444";
}

export default function ScoreGauge({
  value,
  label,
  unit = "/100",
  height = 132,
}: {
  value: number | null | undefined;
  label?: string;
  unit?: string;
  height?: number;
}) {
  const v = value == null || Number.isNaN(value) ? null : Math.max(0, Math.min(100, value));
  const data = [{ name: label ?? "score", value: v ?? 0, fill: v == null ? "#cbd5e1" : scoreColour(v) }];
  return (
    <div className="relative w-full" style={{ height }}>
      <ResponsiveContainer>
        <RadialBarChart innerRadius="68%" outerRadius="100%" data={data} startAngle={90} endAngle={-270}>
          <PolarAngleAxis type="number" domain={[0, 100]} angleAxisId={0} tick={false} />
          <RadialBar background dataKey="value" cornerRadius={10} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
        <span className="text-2xl font-bold text-white tabular-nums leading-none">
          {v == null ? "n/a" : Math.round(v)}
          {v != null && <span className="text-xs font-medium text-slate-400 ml-0.5">{unit}</span>}
        </span>
        {label && <span className="mt-1 max-w-[7rem] truncate text-center text-[11px] font-medium text-slate-200 uppercase tracking-wide">{label}</span>}
      </div>
    </div>
  );
}
