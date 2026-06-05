import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
  AreaChart, Area, XAxis, YAxis,
  BarChart, Bar,
} from "recharts";
import {
  BarChart3, Search as SearchIcon, AlertTriangle, Gauge, Clock,
  TrendingUp, Layers, Globe, ShieldAlert, Loader2, Users,
  MessageSquare, Star, Languages, Package, Tag,
} from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../hooks/useAuth";

// ── Types mirroring api/routers/search_analytics.py ────────────────────────────
interface Kpis {
  total_searches: number;
  unique_queries: number;
  avg_results: number;
  zero_result_rate: number;
  avg_latency_ms: number;
  risk_result_share: number;
  live_searches: number;
  ai_searches: number;
  semantic_searches: number;
}
interface TimelinePoint { date: string; searches: number; positive: number; neutral: number; negative: number; }
interface QueryStat { q: string; count: number; avg_results: number; last_searched: string | null; }
interface Slice { label: string; count: number; }
interface Dashboard {
  scope: string; scope_label: string; period: string; generated_at: string;
  kpis: Kpis;
  timeline: TimelinePoint[];
  top_queries: QueryStat[];
  zero_result_queries: QueryStat[];
  sentiment: Slice[]; topics: Slice[]; sources: Slice[]; geo: Slice[]; risk: Slice[];
}
interface RoleUsageItem {
  role: string; role_label: string; total_searches: number; unique_queries: number;
  avg_results: number; zero_result_rate: number; risk_result_share: number;
}

const PERIODS = ["7d", "30d", "90d", "365d", "all"] as const;
type Period = (typeof PERIODS)[number];

// Admin can scope analytics to any persona; "all" = combined view.
const ROLE_OPTIONS: { value: string; label: string }[] = [
  { value: "all", label: "All roles" },
  { value: "pharmacist", label: "Pharmacist" },
  { value: "marketing", label: "Marketing" },
  { value: "brand_manager", label: "Brand Manager" },
  { value: "admin", label: "Admin" },
];

const SENTIMENT_COLORS: Record<string, string> = {
  positive: "#10b981", neutral: "#94a3b8", negative: "#ef4444",
};
const BAR_COLOR = "#6366f1";

function pct(x: number) { return `${(x * 100).toFixed(1)}%`; }
function fmt(n: number) { return n.toLocaleString("en-GB"); }

function KpiCard({ icon: Icon, label, value, sub, tone }: {
  icon: any; label: string; value: string; sub?: string; tone?: "danger" | "warn" | "ok";
}) {
  const toneClass = tone === "danger" ? "text-red-600" : tone === "warn" ? "text-amber-600" : "text-slate-900";
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4 lift">
      <div className="flex items-center gap-2 text-slate-400">
        <Icon size={15} />
        <span className="text-xs font-medium uppercase tracking-wider">{label}</span>
      </div>
      <p className={`text-2xl font-semibold tabular-nums mt-1.5 ${toneClass}`}>{value}</p>
      {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
    </div>
  );
}

function ChartCard({ title, icon: Icon, children, empty }: {
  title: string; icon: any; children: React.ReactNode; empty?: boolean;
}) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1.5 mb-3">
        <Icon size={14} /> {title}
      </h3>
      {empty ? (
        <div className="h-[180px] flex items-center justify-center text-sm text-slate-400">No data in this period</div>
      ) : children}
    </div>
  );
}

function HBars({ data }: { data: Slice[] }) {
  return (
    <ResponsiveContainer width="100%" height={Math.max(120, data.length * 30)}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
        <XAxis type="number" hide />
        <YAxis type="category" dataKey="label" width={110} tick={{ fontSize: 11, fill: "#64748b" }} />
        <Tooltip cursor={{ fill: "#f1f5f9" }} contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
        <Bar dataKey="count" fill={BAR_COLOR} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function ModeMix({ live, ai, semantic, total }: { live: number; ai: number; semantic: number; total: number }) {
  const denom = total || 1;
  const rows = [
    { label: "Live", value: live, color: "bg-brand-500" },
    { label: "AI", value: ai, color: "bg-accent-500" },
    { label: "Semantic", value: semantic, color: "bg-emerald-500" },
  ];
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className="flex items-center gap-2 text-slate-400 mb-3">
        <Layers size={15} />
        <span className="text-xs font-medium uppercase tracking-wider">Mode usage — share of all searches</span>
      </div>
      <div className="space-y-2.5">
        {rows.map((r) => {
          const p = Math.round((r.value / denom) * 100);
          return (
            <div key={r.label} className="flex items-center gap-3">
              <span className="w-20 text-xs text-slate-500 shrink-0">{r.label}</span>
              <div className="flex-1 h-2.5 rounded-full bg-slate-100 overflow-hidden">
                <div className={`h-full ${r.color} rounded-full transition-all`} style={{ width: `${p}%` }} />
              </div>
              <span className="w-12 text-right text-sm font-semibold tabular-nums text-slate-700">{p}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Review sentiment types (mirror /analytics/reviews) ─────────────────────────
interface KpiCardModel { label: string; value: string; sub?: string | null; tone?: string | null; }
interface ReviewTimelinePoint { date: string; reviews: number; positive: number; neutral: number; negative: number; }
interface BrandRow {
  brand: string; reviews: number; avg_rating: number;
  positive: number; neutral: number; negative: number; sov_percent: number; momentum?: string | null;
}
interface ProductRow { product: string; brand: string | null; reviews: number; avg_rating: number; neg_share: number; }
interface TriageItem {
  text: string; rating: number | null; brand: string | null; product: string | null;
  language: string | null; published_at: string | null; is_adverse_event: boolean;
}
interface LangSentiment { language: string; positive: number; neutral: number; negative: number; }
interface ReviewData {
  scope: string; scope_label: string; lens: string; period: string; generated_at: string;
  sections: string[]; kpis: KpiCardModel[];
  sentiment: Slice[]; timeline: ReviewTimelinePoint[]; sources: Slice[]; languages: Slice[];
  brands: BrandRow[]; topics: Slice[]; products: ProductRow[]; triage: TriageItem[];
  lang_sentiment: LangSentiment[];
  total_reviews: number; avg_rating: number; enriched_reviews: number; embedded_reviews: number;
}

function ReviewKpiCard({ card }: { card: KpiCardModel }) {
  const tone = card.tone === "danger" ? "text-red-600" : card.tone === "warn" ? "text-amber-600"
    : card.tone === "ok" ? "text-emerald-600" : "text-slate-900";
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4 lift">
      <span className="text-xs font-medium uppercase tracking-wider text-slate-400">{card.label}</span>
      <p className={`text-2xl font-semibold tabular-nums mt-1.5 truncate ${tone}`} title={card.value}>{card.value}</p>
      {card.sub && <p className="text-xs text-slate-400 mt-0.5">{card.sub}</p>}
    </div>
  );
}

function MomentumBadge({ m }: { m?: string | null }) {
  if (!m) return <span className="text-slate-300">—</span>;
  const map: Record<string, string> = {
    up: "text-emerald-600 bg-emerald-50", down: "text-red-600 bg-red-50", flat: "text-slate-500 bg-slate-100",
  };
  const label = m === "up" ? "▲ rising" : m === "down" ? "▼ falling" : "● flat";
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${map[m] ?? ""}`}>{label}</span>;
}

function SentimentMini({ p, n, g }: { p: number; n: number; g: number }) {
  const t = p + n + g || 1;
  return (
    <div className="flex h-2 w-24 rounded-full overflow-hidden bg-slate-100" title={`${p} positive · ${n} neutral · ${g} negative`}>
      <div className="bg-emerald-500" style={{ width: `${(p / t) * 100}%` }} />
      <div className="bg-slate-300" style={{ width: `${(n / t) * 100}%` }} />
      <div className="bg-red-500" style={{ width: `${(g / t) * 100}%` }} />
    </div>
  );
}

interface ProductSuggestion { product: string; brand: string | null; reviews: number; avg_rating: number; }

function ProductSearch({ selected, onSelect, onClear }: {
  selected: string | null; onSelect: (p: string) => void; onClear: () => void;
}) {
  const [term, setTerm] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(term), 200);
    return () => clearTimeout(t);
  }, [term]);

  const { data: suggestions } = useQuery<ProductSuggestion[]>({
    queryKey: ["review-product-suggest", debounced],
    queryFn: () => apiClient.get("/analytics/reviews/products", { params: { q: debounced } }).then((r) => r.data),
    enabled: debounced.trim().length >= 2 && !selected,
  });

  if (selected) {
    return (
      <div className="flex items-center gap-2 bg-brand-50 border border-brand-200 rounded-lg px-3 py-2">
        <Package size={14} className="text-brand-500 shrink-0" />
        <span className="text-sm text-slate-700">Scoped to <span className="font-semibold">{selected}</span></span>
        <button onClick={() => { onClear(); setTerm(""); }} className="ml-1 text-slate-400 hover:text-slate-700" aria-label="Clear product filter">✕</button>
      </div>
    );
  }

  return (
    <div className="relative">
      <div className="flex items-center gap-2 border border-slate-300 rounded-lg px-3 py-2 bg-white focus-within:ring-2 focus-within:ring-brand-500">
        <SearchIcon size={14} className="text-slate-400 shrink-0" />
        <input
          value={term}
          onChange={(e) => { setTerm(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Search a product…"
          className="text-sm bg-transparent outline-none w-56 text-slate-700 placeholder:text-slate-400"
        />
      </div>
      {open && suggestions && suggestions.length > 0 && (
        <div className="absolute z-20 mt-1 w-80 max-h-72 overflow-y-auto bg-white border border-slate-200 rounded-lg shadow-lg">
          {suggestions.map((s) => (
            <button
              key={s.product}
              onMouseDown={() => { onSelect(s.product); setTerm(""); setOpen(false); }}
              className="w-full text-left px-3 py-2 hover:bg-slate-50 border-b border-slate-50 last:border-0"
            >
              <div className="text-sm text-slate-700 truncate">{s.product}</div>
              <div className="text-xs text-slate-400 flex gap-2">
                {s.brand && <span>{s.brand}</span>}
                <span>· {fmt(s.reviews)} reviews</span>
                <span>· {s.avg_rating.toFixed(2)}★</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

type ProdSortKey = "product" | "avg_rating" | "reviews" | "neg_share";

function ProductGrid({ rows }: { rows: ProductRow[] }) {
  const [sortKey, setSortKey] = useState<ProdSortKey>("reviews");
  const [dir, setDir] = useState<"asc" | "desc">("desc");
  const toggle = (k: ProdSortKey) => {
    if (k === sortKey) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(k); setDir(k === "product" ? "asc" : "desc"); }
  };
  const sorted = [...rows].sort((a, b) => {
    let cmp: number;
    if (sortKey === "product") cmp = a.product.localeCompare(b.product);
    else cmp = (a[sortKey] as number) - (b[sortKey] as number);
    return dir === "asc" ? cmp : -cmp;
  });
  const Arrow = ({ k }: { k: ProdSortKey }) => (
    <span className="text-slate-300">{sortKey === k ? (dir === "asc" ? " ▲" : " ▼") : " ↕"}</span>
  );
  const Th = ({ k, label, right }: { k: ProdSortKey; label: string; right?: boolean }) => (
    <th
      onClick={() => toggle(k)}
      className={`py-2 font-medium cursor-pointer select-none hover:text-slate-700 ${right ? "text-right" : ""}`}
    >
      {label}<Arrow k={k} />
    </th>
  );
  return (
    <div className="overflow-x-auto max-h-[480px] overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-white">
          <tr className="text-left text-xs text-slate-400 border-b border-slate-100">
            <Th k="product" label="Product" />
            <th className="py-2 font-medium">Brand</th>
            <Th k="reviews" label="Reviews" right />
            <Th k="avg_rating" label="Avg ★" right />
            <Th k="neg_share" label="Negative" right />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {sorted.map((p) => (
            <tr key={p.product}>
              <td className="py-2 text-slate-700 max-w-[300px] truncate" title={p.product}>{p.product}</td>
              <td className="py-2 text-slate-500">{p.brand ?? "—"}</td>
              <td className="py-2 text-right tabular-nums text-slate-500">{fmt(p.reviews)}</td>
              <td className="py-2 text-right tabular-nums font-medium">{p.avg_rating.toFixed(2)}</td>
              <td className="py-2 text-right tabular-nums text-red-600">{p.neg_share}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type BrandSortKey = "brand" | "reviews" | "sov_percent" | "avg_rating";

function BrandTable({ rows }: { rows: BrandRow[] }) {
  const [sortKey, setSortKey] = useState<BrandSortKey>("reviews");
  const [dir, setDir] = useState<"asc" | "desc">("desc");
  const toggle = (k: BrandSortKey) => {
    if (k === sortKey) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(k); setDir(k === "brand" ? "asc" : "desc"); }
  };
  const sorted = [...rows].sort((a, b) => {
    let cmp: number;
    if (sortKey === "brand") cmp = a.brand.localeCompare(b.brand);
    else cmp = (a[sortKey] as number) - (b[sortKey] as number);
    return dir === "asc" ? cmp : -cmp;
  });
  const Arrow = ({ k }: { k: BrandSortKey }) => (
    <span className="text-slate-300">{sortKey === k ? (dir === "asc" ? " ▲" : " ▼") : " ↕"}</span>
  );
  const Th = ({ k, label, right }: { k: BrandSortKey; label: string; right?: boolean }) => (
    <th
      onClick={() => toggle(k)}
      className={`py-2 font-medium cursor-pointer select-none hover:text-slate-700 ${right ? "text-right" : ""}`}
    >
      {label}<Arrow k={k} />
    </th>
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-400 border-b border-slate-100">
            <Th k="brand" label="Brand" />
            <Th k="reviews" label="Reviews" right />
            <Th k="sov_percent" label="SoV" right />
            <Th k="avg_rating" label="Avg ★" right />
            <th className="py-2 font-medium">Sentiment</th>
            <th className="py-2 font-medium text-right">Demand momentum</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {sorted.map((b) => (
            <tr key={b.brand}>
              <td className="py-2 font-medium text-slate-700">{b.brand}</td>
              <td className="py-2 text-right tabular-nums text-slate-500">{fmt(b.reviews)}</td>
              <td className="py-2 text-right tabular-nums text-brand-600">{b.sov_percent}%</td>
              <td className="py-2 text-right tabular-nums">{b.avg_rating.toFixed(2)}</td>
              <td className="py-2"><SentimentMini p={b.positive} n={b.neutral} g={b.negative} /></td>
              <td className="py-2 text-right"><MomentumBadge m={b.momentum} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReviewsPanel({ data }: { data: ReviewData }) {
  const has = (k: string) => data.sections.includes(k);
  return (
    <>
      {/* role-tailored KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        {data.kpis.map((c) => <ReviewKpiCard key={c.label} card={c} />)}
      </div>

      {/* sentiment + sources/topics */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title="Review sentiment (rating-derived)" icon={Gauge} empty={data.sentiment.length === 0}>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie data={data.sentiment} dataKey="count" nameKey="label" cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={2}>
                {data.sentiment.map((s) => <Cell key={s.label} fill={SENTIMENT_COLORS[s.label] ?? "#cbd5e1"} />)}
              </Pie>
              <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>
        {has("sources") && (
          <ChartCard title="Reviews by source" icon={Layers} empty={data.sources.length === 0}>
            <HBars data={data.sources} />
          </ChartCard>
        )}
        {has("topics") && !has("sources") && (
          <ChartCard title="Topics (LLM-enriched subset)" icon={Tag} empty={data.topics.length === 0}>
            <HBars data={data.topics.slice(0, 8)} />
          </ChartCard>
        )}
      </div>

      {/* timeline */}
      {has("timeline") && (
        <ChartCard title="Review volume & sentiment over time (monthly)" icon={TrendingUp} empty={data.timeline.length === 0}>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={data.timeline} margin={{ left: -16, right: 8, top: 4 }}>
              <defs>
                <linearGradient id="rReviews" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#6366f1" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="#6366f1" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#94a3b8" }} />
              <YAxis tick={{ fontSize: 10, fill: "#94a3b8" }} allowDecimals={false} />
              <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
              <Area type="monotone" dataKey="reviews" stroke="#6366f1" strokeWidth={2} fill="url(#rReviews)" name="reviews" />
              <Area type="monotone" dataKey="positive" stackId="s" stroke="#10b981" fill="#10b981" fillOpacity={0.25} name="positive" />
              <Area type="monotone" dataKey="negative" stackId="s" stroke="#ef4444" fill="#ef4444" fillOpacity={0.25} name="negative" />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>
      )}

      {/* brand performance table */}
      {has("brands") && data.brands.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1.5 mb-3">
            <Star size={14} /> Brand performance — share of voice, rating & momentum · click a column to sort
          </h3>
          <BrandTable rows={data.brands} />
        </div>
      )}

      {/* topics (when sources block already used the right column) */}
      {has("topics") && has("sources") && (
        <ChartCard title="Topics (LLM-enriched subset)" icon={Tag} empty={data.topics.length === 0}>
          <HBars data={data.topics.slice(0, 8)} />
        </ChartCard>
      )}

      {/* product ratings grid — sortable by product name / rating / reviews / negative */}
      {has("products") && (
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1.5 mb-3">
            <Package size={14} /> Product ratings (≥3 reviews) · click a column to sort
          </h3>
          {data.products.length === 0 ? (
            <p className="text-sm text-slate-400 py-6 text-center">No products with enough reviews in this period.</p>
          ) : (
            <ProductGrid rows={data.products} />
          )}
        </div>
      )}

      {/* triage queue (pharmacist) */}
      {has("triage") && (
        <div className="bg-white rounded-xl border border-amber-200 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-amber-700 flex items-center gap-1.5 mb-1">
            <AlertTriangle size={14} /> Negative-review triage queue
          </h3>
          <p className="text-xs text-slate-400 mb-3">Lowest-rated reviews (1–2★); adverse-event-flagged surface first.</p>
          {data.triage.length === 0 ? (
            <p className="text-sm text-emerald-600 py-6 text-center">No low-rated reviews in this period.</p>
          ) : (
            <div className="divide-y divide-slate-50 max-h-[420px] overflow-y-auto">
              {data.triage.map((t, i) => (
                <div key={i} className="py-2.5">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-xs font-semibold tabular-nums text-red-600 bg-red-50 px-1.5 py-0.5 rounded">{t.rating ?? "?"}★</span>
                    {t.brand && <span className="text-xs text-slate-500">{t.brand}</span>}
                    {t.language && <span className="text-[10px] uppercase text-slate-400">{t.language}</span>}
                    {t.is_adverse_event && (
                      <span className="text-[10px] font-semibold text-red-700 bg-red-100 px-1.5 py-0.5 rounded-full flex items-center gap-1">
                        <ShieldAlert size={10} /> ADVERSE EVENT
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-slate-700">{t.text}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* nl-vs-fr sentiment (marketing) */}
      {has("lang_sentiment") && data.lang_sentiment.length > 0 && (
        <ChartCard title="Sentiment by language" icon={Languages}>
          <ResponsiveContainer width="100%" height={Math.max(120, data.lang_sentiment.length * 48)}>
            <BarChart data={data.lang_sentiment} layout="vertical" margin={{ left: 8, right: 16 }} stackOffset="expand">
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="language" width={50} tick={{ fontSize: 12, fill: "#64748b" }} />
              <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
              <Bar dataKey="positive" stackId="a" fill="#10b981" />
              <Bar dataKey="neutral" stackId="a" fill="#94a3b8" />
              <Bar dataKey="negative" stackId="a" fill="#ef4444" />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      )}
    </>
  );
}

export default function Analytics() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [view, setView] = useState<"search" | "reviews">("search");
  const [scope, setScope] = useState<string>("all");
  const [period, setPeriod] = useState<Period>("30d");
  const [productFilter, setProductFilter] = useState<string | null>(null);

  // Non-admins are scoped server-side regardless of param; we only send role for admins.
  const roleParam = isAdmin && scope !== "all" ? scope : undefined;

  const { data, isLoading, isError } = useQuery<Dashboard>({
    queryKey: ["analytics-dashboard", isAdmin ? scope : (user?.role ?? "self"), period],
    queryFn: () => apiClient.get("/analytics/dashboard", { params: { role: roleParam, period } }).then((r) => r.data),
    enabled: view === "search",
  });

  const { data: roleUsage } = useQuery<RoleUsageItem[]>({
    queryKey: ["analytics-role-usage", period],
    queryFn: () => apiClient.get("/analytics/role-usage", { params: { period } }).then((r) => r.data),
    enabled: isAdmin && view === "search",
  });

  const { data: reviewData, isLoading: revLoading, isError: revError } = useQuery<ReviewData>({
    queryKey: ["analytics-reviews", isAdmin ? scope : (user?.role ?? "self"), period, productFilter],
    queryFn: () => apiClient.get("/analytics/reviews", { params: { role: roleParam, period, product: productFilter ?? undefined } }).then((r) => r.data),
    enabled: view === "reviews",
  });

  // Reviews are historical (2010–2026) so "all" is the useful default; search defaults to 30d.
  const switchView = (v: "search" | "reviews") => {
    setView(v);
    setPeriod(v === "reviews" ? "all" : "30d");
    if (v === "search") setProductFilter(null);
  };

  const k = data?.kpis;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <BarChart3 size={22} className="text-brand-500" /> Analytics
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {view === "search"
              ? "Derived from every search — demand, sentiment, coverage gaps and risk"
              : "Pharmacy product reviews (Farmaline + Medi-Market) — sentiment per role lens"}
            {view === "search" && data && <> · <span className="font-medium text-slate-600">{data.scope_label}</span></>}
            {view === "reviews" && reviewData && <> · <span className="font-medium text-slate-600">{reviewData.scope_label}</span></>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Search ↔ Reviews view toggle */}
          <div className="flex rounded-lg border border-slate-300 overflow-hidden">
            <button
              onClick={() => switchView("search")}
              className={`px-3 py-2 text-xs font-medium flex items-center gap-1.5 transition-colors ${
                view === "search" ? "bg-brand-500 text-white" : "bg-white text-slate-500 hover:bg-slate-50"
              }`}
            >
              <SearchIcon size={13} /> Search
            </button>
            <button
              onClick={() => switchView("reviews")}
              className={`px-3 py-2 text-xs font-medium flex items-center gap-1.5 transition-colors ${
                view === "reviews" ? "bg-brand-500 text-white" : "bg-white text-slate-500 hover:bg-slate-50"
              }`}
            >
              <MessageSquare size={13} /> Reviews
            </button>
          </div>
          {view === "reviews" && (
            <ProductSearch
              selected={productFilter}
              onSelect={(p) => setProductFilter(p)}
              onClear={() => setProductFilter(null)}
            />
          )}
          {isAdmin && (
            <select
              value={scope}
              onChange={(e) => setScope(e.target.value)}
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm font-medium text-slate-700 focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white"
              aria-label="Role scope"
            >
              {ROLE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          )}
          <div className="flex rounded-lg border border-slate-300 overflow-hidden">
            {PERIODS.map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-3 py-2 text-xs font-medium transition-colors ${
                  period === p ? "bg-brand-500 text-white" : "bg-white text-slate-500 hover:bg-slate-50"
                }`}
              >
                {p === "all" ? "All" : p}
              </button>
            ))}
          </div>
        </div>
      </div>

      {((view === "search" && isLoading) || (view === "reviews" && revLoading)) && (
        <div className="h-64 flex items-center justify-center text-slate-400">
          <Loader2 className="animate-spin" />
          <span className="ml-2 text-sm">{view === "search" ? "Crunching the search log…" : "Aggregating reviews…"}</span>
        </div>
      )}
      {((view === "search" && isError) || (view === "reviews" && revError)) && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
          Could not load analytics. Is the API running and migrated?
        </div>
      )}

      {view === "reviews" && reviewData && <ReviewsPanel data={reviewData} />}

      {view === "search" && data && k && (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            <KpiCard icon={SearchIcon} label="Searches" value={fmt(k.total_searches)} sub={`${fmt(k.unique_queries)} unique`} />
            <KpiCard icon={Gauge} label="Avg results" value={k.avg_results.toFixed(1)} sub="per search" />
            <KpiCard icon={AlertTriangle} label="Zero-result" value={pct(k.zero_result_rate)} sub="coverage gaps" tone={k.zero_result_rate > 0.2 ? "warn" : undefined} />
            <KpiCard icon={ShieldAlert} label="Risk share" value={pct(k.risk_result_share)} sub="of results flagged" tone={k.risk_result_share > 0.1 ? "danger" : undefined} />
            <KpiCard icon={Clock} label="Avg latency" value={`${Math.round(k.avg_latency_ms)}ms`} />
          </div>

          {/* Mode usage — each mode as its own share of total searches */}
          <ModeMix live={k.live_searches} ai={k.ai_searches} semantic={k.semantic_searches} total={k.total_searches} />

          {/* Timeline */}
          <ChartCard title="Searches & result sentiment over time" icon={TrendingUp} empty={data.timeline.length === 0}>
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={data.timeline} margin={{ left: -16, right: 8, top: 4 }}>
                <defs>
                  <linearGradient id="aSearches" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#6366f1" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#6366f1" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#94a3b8" }} tickFormatter={(d) => d.slice(5)} />
                <YAxis tick={{ fontSize: 10, fill: "#94a3b8" }} allowDecimals={false} />
                <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
                <Area type="monotone" dataKey="searches" stroke="#6366f1" strokeWidth={2} fill="url(#aSearches)" name="searches" />
                <Area type="monotone" dataKey="positive" stackId="s" stroke="#10b981" fill="#10b981" fillOpacity={0.25} name="positive" />
                <Area type="monotone" dataKey="negative" stackId="s" stroke="#ef4444" fill="#ef4444" fillOpacity={0.25} name="negative" />
              </AreaChart>
            </ResponsiveContainer>
          </ChartCard>

          {/* breakdown grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ChartCard title="Result sentiment" icon={Gauge} empty={data.sentiment.length === 0}>
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={data.sentiment} dataKey="count" nameKey="label" cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={2}>
                    {data.sentiment.map((s) => <Cell key={s.label} fill={SENTIMENT_COLORS[s.label] ?? "#cbd5e1"} />)}
                  </Pie>
                  <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
            </ChartCard>
            <ChartCard title="Top sources (share of voice)" icon={Layers} empty={data.sources.length === 0}>
              <HBars data={data.sources.slice(0, 8)} />
            </ChartCard>
            <ChartCard title="Top topics" icon={Layers} empty={data.topics.length === 0}>
              <HBars data={data.topics.slice(0, 8)} />
            </ChartCard>
            <ChartCard title="Geography of results" icon={Globe} empty={data.geo.length === 0}>
              <HBars data={data.geo.slice(0, 8)} />
            </ChartCard>
          </div>

          {/* Top + zero-result queries */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1.5 mb-3">
                <TrendingUp size={14} /> Top queries (demand signal)
              </h3>
              {data.top_queries.length === 0 ? (
                <p className="text-sm text-slate-400 py-6 text-center">No searches yet</p>
              ) : (
                <div className="divide-y divide-slate-50">
                  {data.top_queries.map((q) => (
                    <div key={q.q} className="flex items-center justify-between py-2 gap-3">
                      <span className="text-sm text-slate-700 truncate">{q.q}</span>
                      <div className="flex items-center gap-3 shrink-0 text-xs">
                        <span className="text-slate-400">{q.avg_results.toFixed(0)} avg</span>
                        <span className="font-semibold tabular-nums text-brand-600 bg-brand-50 px-2 py-0.5 rounded-full">{q.count}×</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="bg-white rounded-xl border border-amber-200 p-4">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-amber-700 flex items-center gap-1.5 mb-1">
                <AlertTriangle size={14} /> Coverage blind spots
              </h3>
              <p className="text-xs text-slate-400 mb-3">Queries returning zero results — molecules/brands the radar can't see.</p>
              {data.zero_result_queries.length === 0 ? (
                <p className="text-sm text-emerald-600 py-6 text-center">No blind spots — every query returned results.</p>
              ) : (
                <div className="divide-y divide-slate-50">
                  {data.zero_result_queries.map((q) => (
                    <div key={q.q} className="flex items-center justify-between py-2 gap-3">
                      <span className="text-sm text-slate-700 truncate">{q.q}</span>
                      <span className="font-semibold tabular-nums text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full text-xs shrink-0">{q.count}×</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Risk breakdown */}
          {data.risk.length > 0 && (
            <ChartCard title="Risk signals surfaced" icon={ShieldAlert}>
              <HBars data={data.risk} />
            </ChartCard>
          )}

          {/* Admin-only: cross-role usage */}
          {isAdmin && roleUsage && roleUsage.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1.5 mb-3">
                <Users size={14} /> Usage by role
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-400 border-b border-slate-100">
                      <th className="py-2 font-medium">Role</th>
                      <th className="py-2 font-medium text-right">Searches</th>
                      <th className="py-2 font-medium text-right">Unique</th>
                      <th className="py-2 font-medium text-right">Avg results</th>
                      <th className="py-2 font-medium text-right">Zero-result</th>
                      <th className="py-2 font-medium text-right">Risk share</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-50">
                    {roleUsage.map((r) => (
                      <tr key={r.role}>
                        <td className="py-2 font-medium text-slate-700 capitalize">{r.role_label}</td>
                        <td className="py-2 text-right tabular-nums">{fmt(r.total_searches)}</td>
                        <td className="py-2 text-right tabular-nums text-slate-500">{fmt(r.unique_queries)}</td>
                        <td className="py-2 text-right tabular-nums text-slate-500">{r.avg_results.toFixed(1)}</td>
                        <td className="py-2 text-right tabular-nums text-amber-600">{pct(r.zero_result_rate)}</td>
                        <td className="py-2 text-right tabular-nums text-red-600">{pct(r.risk_result_share)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}