import { useState, useEffect, useRef } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
  AreaChart, Area, XAxis, YAxis,
  BarChart, Bar,
} from "recharts";
import { apiClient } from "../api/client";
import { useI18n } from "../i18n";
import { useAuth } from "../hooks/useAuth";
import {
  Search as SearchIcon, AlertTriangle, ExternalLink, Filter,
  Loader2, Globe, Rss, Clock, Sparkles,
  CheckCircle2, Info, Languages, ShieldAlert, History, Command,
  Stethoscope, Shield, Eye, ThumbsUp, MessageSquare, Youtube, PlayCircle,
  Megaphone, Briefcase, Radar,
  type LucideIcon,
} from "lucide-react";

// Deep-Insights topic categories → colour chip.
const INSIGHT_CAT: Record<string, string> = {
  regulatory: "bg-indigo-500/15 text-indigo-300 border-indigo-400/30",
  safety: "bg-rose-500/15 text-rose-300 border-rose-400/30",
  supply: "bg-amber-500/15 text-amber-300 border-amber-400/30",
  market: "bg-sky-500/15 text-sky-300 border-sky-400/30",
  clinical: "bg-violet-500/15 text-violet-300 border-violet-400/30",
  other: "bg-white/10 text-slate-300 border-white/15",
};

// ── constants ────────────────────────────────────────────────────────────────

const LIVE_SOURCES = ["news", "rss", "wikipedia", "pubmed", "clinical_trials", "openfda", "youtube", "reddit", "app_store", "trustpilot", "forum", "google_trends"];
const SENTIMENTS = ["positive", "neutral", "negative"];

const PERIOD_OPTIONS = [
  { tKey: "period.7d",  value: "7d"  },
  { tKey: "period.30d", value: "30d" },
  { tKey: "period.180d", value: "180d" },
  { tKey: "period.365d", value: "365d" },
  { tKey: "period.all",  value: "all" },
] as const;

const SENTIMENT_STYLE: Record<string, string> = {
  positive: "bg-green-100 text-green-700",
  neutral: "bg-gray-100 text-gray-600",
  negative: "bg-red-100 text-red-700",
};

const SOURCE_ICON: Record<string, string> = {
  news: "Google News",
  reddit: "Reddit",
  rss: "RSS",
  forum: "Forum",
  google_trends: "Trends",
  wikipedia: "Wikipedia",
  pubmed: "PubMed",
  youtube: "YouTube",
  clinical_trials: "ClinicalTrials.gov",
  openfda: "openFDA",
  app_store: "App Store reviews",
  trustpilot: "Trustpilot",
};

const SENTIMENT_COLOUR: Record<string, string> = {
  Positive: "text-green-600 bg-green-50 border-green-200",
  Mixed: "text-yellow-600 bg-yellow-50 border-yellow-200",
  Negative: "text-red-600 bg-red-50 border-red-200",
  Neutral: "text-gray-600 bg-gray-50 border-gray-200",
};

const STORAGE_KEY = "pw_search_state";
const AI_STORAGE_KEY = "pw_ai_search_state";
const LENS_STORAGE_KEY = "pw_lens_role";

// ── Role lens ──────────────────────────────────────────────────────────────────

type Role = "pharmacist" | "marketing" | "brand_manager" | "admin";

const ROLE_ORDER: Role[] = ["pharmacist", "marketing", "brand_manager", "admin"];

const ROLE_ICON: Record<Role, LucideIcon> = {
  pharmacist: Stethoscope,
  marketing: Megaphone,
  brand_manager: Briefcase,
  admin: Shield,
};

// Gradient used for the active-lens chip / switcher pill per role.
const ROLE_ACCENT: Record<Role, string> = {
  pharmacist: "from-emerald-500 to-teal-600",
  marketing: "from-amber-500 to-orange-600",
  brand_manager: "from-violet-500 to-fuchsia-600",
  admin: "from-slate-600 to-slate-800",
};

function isRole(r: unknown): r is Role {
  return r === "pharmacist" || r === "marketing" || r === "brand_manager" || r === "admin";
}

function getLoggedInRole(): Role {
  try {
    const r = localStorage.getItem("user_role");
    if (isRole(r)) return r;
  } catch {}
  return "admin";
}

// 142 → "142", 3200 → "3.2k", 142000 → "142k", 1_200_000 → "1.2M"
function formatCompact(n?: number): string {
  if (n == null || isNaN(n)) return "0";
  if (n < 1000) return String(n);
  if (n < 1_000_000) return (n / 1000).toFixed(n < 10_000 ? 1 : 0).replace(/\.0$/, "") + "k";
  return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
}

// ── types ─────────────────────────────────────────────────────────────────────

interface LiveResult {
  source_type: string;
  source_url?: string;
  country?: string;
  language?: string;
  published_at?: string;
  text: string;
  sentiment: string;
  topic: string;
  risk_type: string;
  is_risk: boolean;
  engagement?: number;
  query: string;
  meta?: {
    video_id?: string;
    title?: string;
    channel_title?: string;
    thumbnail?: string;
    views?: number;
    likes?: number;
    comments?: number;
  };
}

interface SourceNotice {
  source: string;
  status: "ok" | "missing_key" | "empty" | "error";
  count: number;
  detail?: string;
}

// Per-search metrics (feature-engineered server-side in core/search_metrics.py)
interface MetricSlice { label: string; count: number; value?: number; }
interface KpiCard { key: string; label: string; value: string; sub?: string; tone?: "good" | "warn" | "danger" | null; }
interface MetricTimePoint { date: string; count: number; positive: number; neutral: number; negative: number; }
interface CrossRow { label: string; positive: number; neutral: number; negative: number; total: number; }
interface SearchMetrics {
  role: Role;
  role_label: string;
  total: number;
  headline: KpiCard[];
  sentiment_index: number;
  net_sentiment_label: string;
  reach_total: number;
  engagement_rate: number;
  risk_share: number;
  official_coverage: number;
  source_diversity: number;
  sentiment_mix: MetricSlice[];
  topic_mix: MetricSlice[];
  source_mix: MetricSlice[];
  channel_reach: MetricSlice[];
  geo_mix: MetricSlice[];
  language_mix: MetricSlice[];
  risk_mix: MetricSlice[];
  timeline: MetricTimePoint[];
  sentiment_by_topic: CrossRow[];
  risk_by_source: MetricSlice[];
}

// DIA framework metric envelope (intelligence/output_schema.py)
interface MetricValue { kind: "abs" | "percent" | "score"; value: number; label: string; unit?: string | null; delta?: number | null; confidence?: number | null; comparison_window?: string | null; }
interface MetricBundle { name: string; metrics: MetricValue[]; context?: Record<string, unknown>; }
interface FrameworkMetrics { bundles: Record<string, MetricBundle>; scalars: Record<string, number | string | boolean | null>; }
interface SearchIntelligence {
  role: Role;
  role_label: string;
  mode: string;
  brand_resolved: boolean;
  brand_id?: number | null;
  brand_name?: string | null;
  headline: KpiCard[];
  snapshot: SearchMetrics;
  framework?: FrameworkMetrics | null;
}

interface LiveResponse {
  query: string;
  total: number;
  results: LiveResult[];
  sources_queried: string[];
  source_notices?: SourceNotice[];
  expanded_terms: string[];
  elapsed_ms: number;
  role?: Role;
  role_label?: string;
  metrics?: SearchIntelligence;
}

interface AISource {
  source_type: string;
  source_url?: string;
  text: string;
  sentiment: string;
  published_at?: string;
  country?: string;
}

interface AIResponse {
  query: string;
  answer: string;
  key_points: string[];
  sentiment_summary: string;
  disclaimer: string;
  sources: AISource[];
  expanded_terms: string[];
  model: string;
  elapsed_ms: number;
  role?: Role;
  role_label?: string;
}

type Tab = "search" | "ai";

// ── small components ──────────────────────────────────────────────────────────

function SentimentBadge({ value }: { value: string }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium capitalize ${SENTIMENT_STYLE[value] ?? "bg-gray-100 text-gray-500"}`}>
      {value}
    </span>
  );
}

function loadSaved() {
  try { return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "{}"); }
  catch { return {}; }
}

// Segmented "View as" control — only rendered for admins. Lets one account
// preview how each persona sees the same query (the demo the brief asked for).
function RoleSwitcher({ value, onChange }: { value: Role; onChange: (r: Role) => void }) {
  const { t } = useI18n();
  return (
    <div className="inline-flex items-center gap-1.5">
      <span className="text-[11px] font-medium text-slate-400 mr-0.5">{t("lens.viewAs")}</span>
      <div className="inline-flex items-center bg-white border border-slate-200 rounded-lg p-1 shadow-soft">
        {ROLE_ORDER.map((r) => {
          const Icon = ROLE_ICON[r];
          const active = value === r;
          return (
            <button
              key={r}
              type="button"
              onClick={() => onChange(r)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold transition-all ${
                active
                  ? `text-white bg-gradient-to-br ${ROLE_ACCENT[r]} shadow-sm`
                  : "text-slate-500 hover:text-slate-800"
              }`}
            >
              <Icon size={13} /> {t(`role.${r}`)}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// Always-visible banner stating which lens is applied + what it prioritises.
function LensBanner({ role }: { role: Role }) {
  const { t } = useI18n();
  const Icon = ROLE_ICON[role];
  return (
    <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-soft">
      <span className={`shrink-0 w-9 h-9 rounded-lg bg-gradient-to-br ${ROLE_ACCENT[role]} flex items-center justify-center shadow-soft`}>
        <Icon size={17} className="text-white" />
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-slate-800">
          {t("lens.label")} <span className="capitalize">{t(`role.${role}`)}</span>
        </p>
        <p className="text-xs text-slate-500 mt-0.5">{t(`lens.focus.${role}`)}</p>
      </div>
    </div>
  );
}

// Renders text containing [n] markers as React nodes, where each marker becomes
// a clickable chip that scrolls to + briefly highlights source #n.
function renderWithCitations(
  text: string,
  sourceCount: number,
  onCite: (n: number) => void,
): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const re = /\[(\d+)\]/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = re.exec(text)) !== null) {
    const n = parseInt(match[1], 10);
    if (match.index > last) parts.push(text.slice(last, match.index));
    if (n >= 1 && n <= sourceCount) {
      parts.push(
        <button
          key={`c${key++}`}
          type="button"
          onClick={() => onCite(n)}
          className="mx-0.5 inline-flex items-center justify-center min-w-[20px] h-[18px] px-1 text-[10px] font-bold text-accent-700 bg-accent-100 hover:bg-accent-200 hover:text-accent-800 rounded align-text-top transition-colors"
          title={`Jump to source ${n}`}
        >
          {n}
        </button>
      );
    } else {
      parts.push(match[0]);
    }
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

// Pretty pill row showing the cross-lingual expansion (only when actually expanded).
// When `onSelect` is provided, each pill becomes a button that drills into that term.
function ExpandedTermsRow({
  original,
  terms,
  onSelect,
}: {
  original: string;
  terms: string[];
  onSelect?: (term: string) => void;
}) {
  const { t } = useI18n();
  const extra = terms.filter((x) => x.toLowerCase() !== original.trim().toLowerCase());
  if (extra.length === 0) return null;
  const label = onSelect ? t("expansion.drillInto") : t("expansion.alsoSearched");
  return (
    <div className="flex items-start gap-2 flex-wrap">
      <span className="flex items-center gap-1 text-xs text-gray-500 pt-1">
        <Languages size={12} /> {label}
      </span>
      {extra.map((t) =>
        onSelect ? (
          <button
            key={t}
            type="button"
            onClick={() => onSelect(t)}
            className="text-xs px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-100 hover:bg-indigo-100 hover:border-indigo-300 transition-colors cursor-pointer"
            title={`Search just for "${t}"`}
          >
            {t}
          </button>
        ) : (
          <span key={t} className="text-xs px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-100">
            {t}
          </span>
        )
      )}
    </div>
  );
}

// ── Recent searches (cross-tab, localStorage-backed) ─────────────────────────

const RECENT_KEY = "pw_recent_searches";
const RECENT_MAX = 5;

function loadRecent(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(raw) ? raw.slice(0, RECENT_MAX).filter((x) => typeof x === "string") : [];
  } catch { return []; }
}

function pushRecent(q: string) {
  const trimmed = q.trim();
  if (trimmed.length < 2) return;
  const cur = loadRecent().filter((x) => x.toLowerCase() !== trimmed.toLowerCase());
  cur.unshift(trimmed);
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(cur.slice(0, RECENT_MAX))); } catch {}
}

function RecentSearches({ onPick }: { onPick: (q: string) => void }) {
  const { t } = useI18n();
  const [items, setItems] = useState<string[]>(() => loadRecent());
  // Re-read on mount so the strip reflects pushes from the other tab
  useEffect(() => { setItems(loadRecent()); }, []);
  if (items.length === 0) return null;
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="flex items-center gap-1 text-xs text-gray-400">
        <History size={12} /> {t("recent")}
      </span>
      {items.map((q) => (
        <button
          key={q}
          type="button"
          onClick={() => onPick(q)}
          className="text-xs px-2.5 py-1 rounded-full bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100 hover:border-gray-300 transition-colors"
        >
          {q}
        </button>
      ))}
    </div>
  );
}

// ── Insight Panel (Live Search) ──────────────────────────────────────────────

const SENTIMENT_FILL: Record<string, string> = {
  positive: "#22c55e",
  neutral: "#94a3b8",
  negative: "#ef4444",
};

function prettyLabel(s: string) {
  return SOURCE_ICON[s] ?? s.replace(/_/g, " ");
}

function ChartTile({ title, children, height = 150 }: { title: string; children: React.ReactNode; height?: number }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-3.5 flex flex-col shadow-soft lift">
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">{title}</p>
      <div style={{ height }}>{children}</div>
    </div>
  );
}

const TONE_CARD: Record<string, string> = {
  good: "border-emerald-200 bg-emerald-50",
  warn: "border-amber-200 bg-amber-50",
  danger: "border-red-200 bg-red-50",
};
const TONE_VAL: Record<string, string> = {
  good: "text-emerald-700",
  warn: "text-amber-700",
  danger: "text-red-700",
};

function MetricKpi({ k }: { k: KpiCard }) {
  const tone = k.tone || "";
  return (
    <div className={`rounded-xl border p-3 shadow-soft lift ${TONE_CARD[tone] ?? "border-slate-200 bg-white"}`}>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 leading-tight">{k.label}</p>
      <p className={`text-xl font-bold tabular-nums mt-1 leading-none ${TONE_VAL[tone] ?? "text-slate-800"}`}>{k.value}</p>
      {k.sub && <p className="text-[10px] text-slate-400 mt-1 leading-tight">{k.sub}</p>}
    </div>
  );
}

// Linked cross-tab: one stacked pos/neutral/neg bar per topic.
function SentimentByTopic({ rows }: { rows: CrossRow[] }) {
  if (!rows.length) return <p className="text-xs text-gray-400">No topic data</p>;
  return (
    <div className="space-y-2">
      {rows.map((r) => {
        const tot = r.total || 1;
        return (
          <div key={r.label} className="flex items-center gap-2">
            <span className="w-24 shrink-0 truncate text-[11px] text-slate-600 capitalize">{prettyLabel(r.label)}</span>
            <div className="flex-1 h-3 rounded overflow-hidden flex bg-slate-100">
              <div style={{ width: `${(r.positive / tot) * 100}%` }} className="bg-green-500" title={`positive ${r.positive}`} />
              <div style={{ width: `${(r.neutral / tot) * 100}%` }} className="bg-slate-400" title={`neutral ${r.neutral}`} />
              <div style={{ width: `${(r.negative / tot) * 100}%` }} className="bg-red-500" title={`negative ${r.negative}`} />
            </div>
            <span className="w-7 text-right text-[11px] tabular-nums text-slate-500">{r.total}</span>
          </div>
        );
      })}
    </div>
  );
}

// Role-aware metrics dashboard — auto-filled from server-computed `metrics`.
function InsightPanel({ intel }: { intel: SearchIntelligence }) {
  const metrics = intel.snapshot;
  const sentimentData = metrics.sentiment_mix.map((s) => ({ name: s.label, value: s.count, key: s.label }));
  const total = metrics.total || 1;
  const posPct = Math.round(((metrics.sentiment_mix.find((s) => s.label === "positive")?.count ?? 0) / total) * 100);
  // Share-of-voice: reach if present, else volume.
  const sovData = metrics.channel_reach.slice(0, 6).map((s) => ({ name: prettyLabel(s.label), value: s.value ?? s.count }));
  const topicData = metrics.topic_mix.filter((s) => s.label !== "general").slice(0, 6).map((s) => ({ name: prettyLabel(s.label), value: s.count }));
  const reachMode = metrics.reach_total > 0;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
        {intel.headline
          .filter((k) => !["bpi", "sov", "momentum", "launch"].includes(k.key))
          .map((k) => <MetricKpi key={k.key} k={k} />)}
      </div>

      {/* Chart grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {/* Sentiment donut */}
        <ChartTile title="Sentiment">
          {sentimentData.every((d) => d.value === 0) ? (
            <p className="text-xs text-gray-400 flex items-center h-full">No data</p>
          ) : (
            <div className="relative w-full h-full">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={sentimentData} innerRadius={36} outerRadius={56} paddingAngle={2} dataKey="value" stroke="none">
                    {sentimentData.map((entry) => (
                      <Cell key={entry.key} fill={SENTIMENT_FILL[entry.key] ?? "#94a3b8"} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(v: number, n: string) => [`${v} mention${v === 1 ? "" : "s"}`, n]}
                    contentStyle={{ fontSize: 11, padding: "6px 10px", borderRadius: 8, border: "1px solid #e2e8f0", boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }}
                    itemStyle={{ color: "#e2e8f0" }}
                    labelStyle={{ color: "#e2e8f0" }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span className="text-xl font-bold text-slate-800 leading-none tabular-nums">{posPct}%</span>
                <span className="text-[10px] text-slate-400 leading-none mt-0.5 uppercase tracking-wider">positive</span>
              </div>
            </div>
          )}
        </ChartTile>

        {/* Share of voice (reach) / channel mix */}
        <ChartTile title={reachMode ? "Share of voice (reach)" : "Channels"}>
          {sovData.length === 0 ? (
            <p className="text-xs text-gray-400 flex items-center h-full">No data</p>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sovData} layout="vertical" margin={{ top: 0, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="srcBar" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#3f6dff" />
                    <stop offset="100%" stopColor="#885dfa" />
                  </linearGradient>
                </defs>
                <XAxis type="number" hide />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: "#475569" }} axisLine={false} tickLine={false} width={66} />
                <Tooltip
                  formatter={(v: number) => [reachMode ? `${formatCompact(v)} reach` : `${v} mention${v === 1 ? "" : "s"}`, reachMode ? "Reach" : "Count"]}
                  contentStyle={{ fontSize: 11, padding: "6px 10px", borderRadius: 8, border: "1px solid #e2e8f0", boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }}
                />
                <Bar dataKey="value" fill="url(#srcBar)" radius={[0, 4, 4, 0]} barSize={12} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartTile>

        {/* Topics (excluding 'general') */}
        <ChartTile title="Topics">
          {topicData.length === 0 ? (
            <p className="text-xs text-gray-400 flex items-center h-full">Mostly general</p>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={topicData} layout="vertical" margin={{ top: 0, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="topicBar" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#0ea5e9" />
                    <stop offset="100%" stopColor="#3f6dff" />
                  </linearGradient>
                </defs>
                <XAxis type="number" hide />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: "#475569" }} axisLine={false} tickLine={false} width={84} />
                <Tooltip
                  formatter={(v: number) => [`${v} mention${v === 1 ? "" : "s"}`, "Count"]}
                  contentStyle={{ fontSize: 11, padding: "6px 10px", borderRadius: 8, border: "1px solid #e2e8f0", boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }}
                />
                <Bar dataKey="value" fill="url(#topicBar)" radius={[0, 4, 4, 0]} barSize={12} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartTile>

        {/* Mentions over time */}
        <ChartTile title="Mentions over time">
          {metrics.timeline.length < 2 ? (
            <p className="text-xs text-gray-400 flex items-center h-full">Not enough dated mentions</p>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={metrics.timeline} margin={{ top: 5, right: 4, left: -22, bottom: 0 }}>
                <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#9ca3af" }} tickFormatter={(d: string) => d.slice(5)} axisLine={false} tickLine={false} minTickGap={20} />
                <YAxis tick={{ fontSize: 9, fill: "#9ca3af" }} axisLine={false} tickLine={false} width={28} allowDecimals={false} />
                <Tooltip
                  labelFormatter={(d: string) => d}
                  contentStyle={{ fontSize: 11, padding: "6px 10px", borderRadius: 8, border: "1px solid #e2e8f0", boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }}
                />
                <Area type="monotone" dataKey="positive" stackId="1" stroke="#22c55e" fill="#22c55e" fillOpacity={0.55} strokeWidth={1} />
                <Area type="monotone" dataKey="neutral" stackId="1" stroke="#94a3b8" fill="#94a3b8" fillOpacity={0.4} strokeWidth={1} />
                <Area type="monotone" dataKey="negative" stackId="1" stroke="#ef4444" fill="#ef4444" fillOpacity={0.55} strokeWidth={1} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </ChartTile>
      </div>

      {/* Linked cross-tabs */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ChartTile title="Sentiment × topic" height={Math.max(110, metrics.sentiment_by_topic.length * 26)}>
          <SentimentByTopic rows={metrics.sentiment_by_topic} />
        </ChartTile>
        <ChartTile title="Where the risk is (by source)" height={Math.max(110, Math.max(1, metrics.risk_by_source.length) * 26)}>
          {metrics.risk_by_source.length === 0 ? (
            <p className="text-xs text-gray-400 flex items-center h-full">No risk signals in this search</p>
          ) : (
            <div className="space-y-2">
              {metrics.risk_by_source.map((s) => {
                const max = Math.max(...metrics.risk_by_source.map((x) => x.count), 1);
                return (
                  <div key={s.label} className="flex items-center gap-2">
                    <span className="w-24 shrink-0 truncate text-[11px] text-slate-600">{prettyLabel(s.label)}</span>
                    <div className="flex-1 h-2.5 rounded bg-slate-100 overflow-hidden">
                      <div className="h-full bg-red-500" style={{ width: `${(s.count / max) * 100}%` }} />
                    </div>
                    <span className="w-7 text-right text-[11px] tabular-nums text-slate-500">{s.count}</span>
                  </div>
                );
              })}
            </div>
          )}
        </ChartTile>
      </div>
    </div>
  );
}

// ── YouTube analytics panel ───────────────────────────────────────────────────
// Built entirely from the enriched YouTube results (views/likes/comments/channel
// the connector now fetches via videos.list). Only rendered when ≥1 YouTube
// result carries metrics.

interface YtVideo {
  title: string;
  channel: string;
  url?: string;
  thumbnail?: string;
  views: number;
  likes: number;
  comments: number;
  published_at?: string;
}

function extractYouTube(results: LiveResult[]): YtVideo[] {
  return results
    .filter((r) => r.source_type === "youtube" && r.meta)
    .map((r) => ({
      title: r.meta?.title || r.text.slice(0, 80),
      channel: r.meta?.channel_title || "—",
      url: r.source_url,
      thumbnail: r.meta?.thumbnail,
      views: r.meta?.views ?? r.engagement ?? 0,
      likes: r.meta?.likes ?? 0,
      comments: r.meta?.comments ?? 0,
      published_at: r.published_at,
    }));
}

function YouTubeAnalyticsPanel({ results }: { results: LiveResult[] }) {
  const { t } = useI18n();
  const videos = extractYouTube(results);
  if (videos.length === 0) return null;

  const totalViews = videos.reduce((a, v) => a + v.views, 0);

  // Top channels by aggregate views.
  const channelMap = new Map<string, number>();
  for (const v of videos) channelMap.set(v.channel, (channelMap.get(v.channel) ?? 0) + v.views);
  const topChannels = Array.from(channelMap, ([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 5);

  // Views over time (by ISO date).
  const dateMap = new Map<string, number>();
  for (const v of videos) {
    if (!v.published_at) continue;
    const d = new Date(v.published_at);
    if (isNaN(d.getTime())) continue;
    const key = d.toISOString().slice(0, 10);
    dateMap.set(key, (dateMap.get(key) ?? 0) + v.views);
  }
  const viewsOverTime = Array.from(dateMap, ([date, views]) => ({ date, views }))
    .sort((a, b) => a.date.localeCompare(b.date));

  // Most-engaged = likes + comments weighted, falling back to views.
  const mostEngaged = [...videos]
    .sort((a, b) => (b.likes + b.comments * 2 || b.views) - (a.likes + a.comments * 2 || a.views))
    .slice(0, 5);

  return (
    <div className="rounded-2xl border border-slate-200 bg-gradient-to-br from-rose-500/10 via-transparent to-transparent shadow-soft overflow-hidden">
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-slate-100">
        <span className="shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-red-500 to-rose-600 flex items-center justify-center shadow-soft">
          <Youtube size={16} className="text-white" />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-800">{t("yt.analytics")}</p>
          <p className="text-[11px] text-slate-400">
            {videos.length} {t("yt.videos")} · {formatCompact(totalViews)} {t("yt.views")}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 p-4">
        {/* Top channels */}
        <ChartTile title={t("yt.topChannels")} height={150}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={topChannels} layout="vertical" margin={{ top: 0, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="ytChannelBar" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#ef4444" />
                  <stop offset="100%" stopColor="#f43f5e" />
                </linearGradient>
              </defs>
              <XAxis type="number" hide />
              <YAxis
                dataKey="name"
                type="category"
                tick={{ fontSize: 10, fill: "#475569" }}
                axisLine={false}
                tickLine={false}
                width={84}
                tickFormatter={(s: string) => (s.length > 12 ? s.slice(0, 11) + "…" : s)}
              />
              <Tooltip
                formatter={(v: number) => [`${formatCompact(v)} ${t("yt.views")}`, "Views"]}
                contentStyle={{ fontSize: 11, padding: "6px 10px", borderRadius: 8, border: "1px solid #e2e8f0", boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }}
              />
              <Bar dataKey="value" fill="url(#ytChannelBar)" radius={[0, 4, 4, 0]} barSize={12} />
            </BarChart>
          </ResponsiveContainer>
        </ChartTile>

        {/* Views over time */}
        <ChartTile title={t("yt.viewsOverTime")} height={150}>
          {viewsOverTime.length < 2 ? (
            <p className="text-xs text-gray-400 flex items-center h-full">{t("insight.timeline.empty")}</p>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={viewsOverTime} margin={{ top: 5, right: 4, left: -18, bottom: 0 }}>
                <defs>
                  <linearGradient id="ytViewsArea" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#ef4444" stopOpacity={0.45} />
                    <stop offset="100%" stopColor="#ef4444" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 9, fill: "#9ca3af" }}
                  tickFormatter={(d: string) => d.slice(5)}
                  axisLine={false}
                  tickLine={false}
                  minTickGap={20}
                />
                <YAxis
                  tick={{ fontSize: 9, fill: "#9ca3af" }}
                  axisLine={false}
                  tickLine={false}
                  width={34}
                  tickFormatter={(v: number) => formatCompact(v)}
                />
                <Tooltip
                  formatter={(v: number) => [`${formatCompact(v)} ${t("yt.views")}`, "Views"]}
                  contentStyle={{ fontSize: 11, padding: "6px 10px", borderRadius: 8, border: "1px solid #e2e8f0", boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }}
                />
                <Area type="monotone" dataKey="views" stroke="#ef4444" fill="url(#ytViewsArea)" strokeWidth={1.5} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </ChartTile>

        {/* Most-engaged videos */}
        <div className="bg-white border border-slate-200 rounded-xl p-3.5 flex flex-col shadow-soft">
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">{t("yt.mostEngaged")}</p>
          <ul className="space-y-2 overflow-hidden">
            {mostEngaged.map((v, i) => (
              <li key={i} className="flex items-center gap-2 min-w-0">
                <span className="shrink-0 text-[10px] font-bold text-slate-400 w-4">{i + 1}</span>
                {v.thumbnail ? (
                  <img src={v.thumbnail} alt="" className="shrink-0 w-10 h-7 rounded object-cover bg-slate-100" loading="lazy" />
                ) : (
                  <span className="shrink-0 w-10 h-7 rounded bg-slate-100 flex items-center justify-center"><PlayCircle size={13} className="text-slate-400" /></span>
                )}
                <div className="flex-1 min-w-0">
                  <a
                    href={v.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block text-xs font-medium text-slate-700 hover:text-red-600 truncate"
                    title={v.title}
                  >
                    {v.title}
                  </a>
                  <span className="flex items-center gap-2 text-[10px] text-slate-400">
                    <span className="flex items-center gap-0.5"><Eye size={10} /> {formatCompact(v.views)}</span>
                    <span className="flex items-center gap-0.5"><ThumbsUp size={10} /> {formatCompact(v.likes)}</span>
                    <span className="flex items-center gap-0.5"><MessageSquare size={10} /> {formatCompact(v.comments)}</span>
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

// ── Per-source diagnostic banner ──────────────────────────────────────────────
// Surfaces "this source returned 0 because…" so users don't think the whole
// search is broken when one connector needs a key or didn't match.

const NOTICE_STATUS_STYLE: Record<string, string> = {
  missing_key: "bg-amber-50 border-amber-200 text-amber-800",
  error:       "bg-red-50 border-red-200 text-red-800",
  empty:       "bg-slate-50 border-slate-200 text-slate-600",
};

function SourceNoticesBanner({ notices }: { notices: SourceNotice[] }) {
  const concerning = notices.filter((n) => n.status !== "ok");
  if (concerning.length === 0) return null;
  return (
    <div className="space-y-1.5">
      {concerning.map((n) => (
        <div
          key={n.source}
          className={`flex items-start gap-2.5 text-xs rounded-lg border px-3 py-2 ${NOTICE_STATUS_STYLE[n.status] ?? NOTICE_STATUS_STYLE.empty}`}
        >
          <Info size={13} className="shrink-0 mt-0.5 opacity-70" />
          <div className="flex-1 min-w-0">
            <span className="font-semibold">{SOURCE_ICON[n.source] ?? n.source}</span>
            {n.status === "missing_key" && <span> — needs an API key</span>}
            {n.status === "error" && !n.detail && <span> — upstream error</span>}
            {n.status === "empty" && <span> — no matches</span>}
            {n.detail && <span className="opacity-75"> · {n.detail}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Risk callout banner — bridges Search → AE Review ─────────────────────────

function RiskCallout({ results, query }: { results: LiveResult[]; query: string }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { user } = useAuth();
  const count = results.length;
  // The AE review queue is pharmacist/admin-only. For other roles, escalation
  // still flags the mentions for pharmacovigilance — but routing them to the
  // queue would hit the role guard and bounce them to their home (Brand Pulse),
  // which read as a broken redirect. So only reviewers navigate; everyone else
  // gets an inline "flagged" confirmation.
  const canReview = user?.role === "pharmacist" || user?.role === "admin";
  const [flagged, setFlagged] = useState(false);

  // Live Search is no-write; an explicit human escalation persists the flagged
  // results into the pharmacovigilance review queue.
  const escalate = useMutation({
    mutationFn: () =>
      apiClient
        .post("/adverse-events/from-search", {
          query,
          results: results.map((r) => ({
            source_type: r.source_type,
            source_url: r.source_url,
            text: r.text,
            country: r.country,
            language: r.language,
            published_at: r.published_at,
            risk_type: r.risk_type,
            query: r.query,
          })),
        })
        .then((r) => r.data),
    onSuccess: () => (canReview ? navigate("/adverse-events") : setFlagged(true)),
  });

  if (count <= 0) return null;
  return (
    <div className="relative flex items-start gap-4 bg-gradient-to-br from-red-50 via-red-50/70 to-orange-50/40 border border-red-200 rounded-2xl p-4 shadow-soft animate-fade-up overflow-hidden">
      <span className="absolute inset-y-0 left-0 w-1 bg-gradient-to-b from-red-500 to-red-600" />
      <div className="relative shrink-0 w-10 h-10 rounded-xl bg-red-100 flex items-center justify-center">
        <ShieldAlert size={19} className="text-red-600" />
        <span className="absolute inset-0 rounded-xl bg-red-400/30 animate-pulse-ring" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-red-900">
          {count === 1 ? t("risk.headline.one") : t("risk.headline", { count })}
        </p>
        <p className="text-xs text-red-700/90 mt-0.5">{t("risk.subline")}</p>
        {escalate.isError && (
          <p className="text-xs text-red-600 mt-1 font-medium">{t("risk.escalateError")}</p>
        )}
      </div>
      {flagged ? (
        <span className="shrink-0 inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold text-emerald-700 bg-emerald-100 border border-emerald-300 rounded-lg">
          ✓ Flagged for the pharmacovigilance team
        </span>
      ) : (
        <button
          onClick={() => escalate.mutate()}
          disabled={escalate.isPending}
          className="shrink-0 inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold text-white bg-gradient-to-br from-red-600 to-red-700 hover:from-red-700 hover:to-red-800 rounded-lg shadow-soft transition-all disabled:opacity-60"
        >
          {escalate.isPending ? <Loader2 size={13} className="animate-spin" /> : null}
          {escalate.isPending ? t("risk.escalating") : canReview ? t("risk.cta") : "Flag for review"}
        </button>
      )}
    </div>
  );
}

// ── AI Mode panel ─────────────────────────────────────────────────────────────

function loadAISaved() {
  try { return JSON.parse(sessionStorage.getItem(AI_STORAGE_KEY) || "{}"); }
  catch { return {}; }
}

function AIModePanel({ role }: { role: Role }) {
  const { t, locale } = useI18n();
  const _aiSaved = loadAISaved();
  const [query, setQuery] = useState<string>(_aiSaved.query ?? "");
  const [data, setData] = useState<AIResponse | null>(_aiSaved.data ?? null);
  const sourceRefs = useRef<Array<HTMLDivElement | null>>([]);
  const [highlightIdx, setHighlightIdx] = useState<number | null>(null);

  const mutation = useMutation<AIResponse, unknown, { q: string }>({
    mutationFn: async ({ q }) => {
      const cfg = { timeout: 30_000 };
      // AI mode is independent — always its own GET research call, never fed
      // Live Search results.
      return apiClient.get("/search/ai", { params: { q, lang: locale, role }, ...cfg }).then((r) => r.data);
    },
    onSuccess: (resp) => setData(resp),
  });

  // Deep Insights — live deep-dive on the latest news for the query.
  const [insights, setInsights] = useState<any | null>(_aiSaved.insights ?? null);
  const diMutation = useMutation<any, unknown, { q: string }>({
    mutationFn: async ({ q }) =>
      apiClient.get("/search/deep-insights", { params: { q, lang: locale, role }, timeout: 150_000 }).then((r) => r.data),
    onSuccess: (resp) => setInsights(resp),
  });

  useEffect(() => {
    try {
      sessionStorage.setItem(AI_STORAGE_KEY, JSON.stringify({ query, data, insights }));
    } catch {}
  }, [query, data, insights]);

  const runQuery = (q: string) => {
    setQuery(q);
    pushRecent(q);
    mutation.mutate({ q });
    diMutation.mutate({ q });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (q.length >= 2) {
      pushRecent(q);
      mutation.mutate({ q });
      diMutation.mutate({ q });
    }
  };

  const isFetching = mutation.isPending;
  const error = mutation.error;
  const overallSentimentClass = data ? (SENTIMENT_COLOUR[data.sentiment_summary] ?? SENTIMENT_COLOUR.Neutral) : "";

  const cite = (n: number) => {
    const el = sourceRefs.current[n - 1];
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlightIdx(n - 1);
    window.setTimeout(() => setHighlightIdx((cur) => (cur === n - 1 ? null : cur)), 1600);
  };

  const sourceCount = data?.sources.length ?? 0;

  return (
    <div className="space-y-6 pt-1 animate-fade-up">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2.5 mb-1">
          <span className="inline-flex items-center justify-center w-7 h-7 rounded-lg bg-gradient-to-br from-accent-500 to-accent-600 shadow-soft">
            <Sparkles size={15} className="text-white" />
          </span>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">{t("tab.ai")}</h2>
          <span className="text-[10px] uppercase tracking-wider bg-accent-100 text-accent-700 px-2 py-0.5 rounded-full font-semibold">{t("ai.beta")}</span>
        </div>
        <p className="text-sm text-slate-500">
          {t("ai.subtitle")} <span className="font-medium text-slate-700">GPT-5.4-mini</span>, {t("ai.grounded")}
        </p>
      </div>

      {/* Search bar */}
      <form onSubmit={handleSubmit}>
        <div className="flex gap-2">
          <div className="relative flex-1 group">
            <Sparkles size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-accent-400 group-focus-within:text-accent-500 transition-colors" />
            <input
              type="text"
              data-search-input="ai"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("ai.placeholder")}
              className="w-full pl-10 pr-4 py-3 bg-white border border-slate-200 rounded-xl text-sm shadow-soft focus:outline-none focus:border-accent-400 focus:shadow-ring-accent transition-shadow"
              autoFocus
            />
          </div>
          <button
            type="submit"
            disabled={query.trim().length < 2 || isFetching}
            className="flex items-center gap-2 px-6 py-3 text-white text-sm font-semibold rounded-xl shadow-elevated bg-gradient-to-br from-accent-500 to-accent-600 hover:from-accent-600 hover:to-accent-700 transition-all disabled:opacity-50 disabled:cursor-not-allowed disabled:from-slate-400 disabled:to-slate-500"
          >
            {isFetching ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
            {isFetching ? t("ai.analysing") : t("ai.askButton")}
          </button>
        </div>
      </form>

      <RecentSearches onPick={(q) => runQuery(q)} />

      {/* Deep Insights — live deep-dive on the latest news, as ranked key topics */}
      {(diMutation.isPending || insights) && (
        <div className="bg-white border border-slate-200 rounded-2xl shadow-soft overflow-hidden">
          <div className="px-5 py-3.5 border-b border-slate-100 flex items-center gap-2.5 bg-gradient-to-br from-accent-500/5 to-transparent">
            <span className="shrink-0 w-7 h-7 rounded-lg bg-gradient-to-br from-accent-500 to-accent-600 flex items-center justify-center shadow-soft">
              <Radar size={15} className="text-white" />
            </span>
            <div className="flex-1 min-w-0">
              <h3 className="text-sm font-semibold text-slate-900">Deep Insights — multi-angle deep dive</h3>
              <p className="text-[11px] text-slate-400">
                {insights?.web_search === false ? "model knowledge" : "live web research · multi-angle"}
                {insights?.role_label ? ` · ${insights.role_label} lens` : ""}
                {insights?.elapsed_ms ? ` · ${(insights.elapsed_ms / 1000).toFixed(1)}s` : ""}
              </p>
            </div>
          </div>
          <div className="p-5">
            {diMutation.isPending ? (
              <div className="flex items-center gap-2 text-sm text-accent-300">
                <Loader2 size={16} className="animate-spin" /> Running a multi-angle deep dive on “{query}” — this takes longer than a normal answer…
              </div>
            ) : diMutation.error ? (
              <p className="text-sm text-rose-400">Couldn’t complete the deep dive — please try again.</p>
            ) : insights ? (
              <div className="space-y-4">
                {insights.recommendation && (
                  <div className="rounded-xl border border-accent-400/30 bg-accent-500/10 px-4 py-3">
                    <p className="text-[10px] uppercase tracking-wide text-accent-300 font-semibold mb-0.5">
                      {insights.role_label ? `${insights.role_label} — recommendation` : "Recommendation"}
                    </p>
                    <p className="text-sm font-semibold text-slate-100">{insights.recommendation}</p>
                  </div>
                )}
                {insights.headline && <p className="text-sm text-slate-300">{insights.headline}</p>}
                {insights.insights?.length > 0 && (
                  <ul className="space-y-3">
                    {insights.insights.map((it: any, i: number) => (
                      <li key={i} className="flex gap-3">
                        <span className="shrink-0 mt-0.5 w-5 h-5 rounded-md bg-accent-500/20 text-accent-200 text-[11px] font-bold flex items-center justify-center">{i + 1}</span>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-semibold text-slate-900">{it.topic}</span>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${INSIGHT_CAT[it.category] ?? INSIGHT_CAT.other}`}>{it.category}</span>
                            {it.recency && <span className="text-[10px] text-slate-400">{it.recency}</span>}
                          </div>
                          <p className="text-sm text-slate-600 leading-relaxed mt-0.5">{it.detail}</p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}

                {/* Research trail — the actual evidence the deep dive gathered */}
                {insights.findings?.length > 0 && (
                  <div className="pt-3 border-t border-white/10">
                    <p className="text-[10px] uppercase tracking-wide text-slate-400 mb-2">
                      Research trail · {insights.findings.length} findings across {insights.angles?.length ?? 0} live-searched angles
                    </p>
                    {insights.angles?.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mb-3">
                        {insights.angles.map((a: string, i: number) => (
                          <span key={i} className="text-[10px] px-2 py-0.5 rounded-full bg-accent-500/10 border border-accent-400/25 text-accent-200 font-medium">{a}</span>
                        ))}
                      </div>
                    )}
                    <ul className="space-y-2">
                      {insights.findings.map((f: any, i: number) => (
                        <li key={i} className="flex gap-2 text-xs leading-relaxed">
                          <span className="shrink-0 mt-0.5 text-accent-300/70">▸</span>
                          <span className="flex-1 min-w-0">
                            <span className="text-slate-300">{f.fact}</span>
                            {f.date && <span className="text-slate-500"> · {f.date}</span>}
                            {f.source_url ? (
                              <a href={f.source_url} target="_blank" rel="noopener noreferrer"
                                 className="inline-flex items-center gap-0.5 text-blue-400 hover:underline ml-1.5">
                                {(f.source_title || "source").slice(0, 40)} <ExternalLink size={9} />
                              </a>
                            ) : f.source_title ? (
                              <span className="text-slate-500 ml-1.5">· {f.source_title.slice(0, 40)}</span>
                            ) : null}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {!insights.insights?.length && !insights.findings?.length && (
                  <p className="text-sm text-slate-400">No recent news surfaced for this query.</p>
                )}
              </div>
            ) : null}
          </div>
        </div>
      )}

      {/* Loading — pulse + skeleton answer */}
      {isFetching && (
        <div className="space-y-4">
          <div className="relative bg-gradient-to-br from-accent-500/10 via-transparent to-accent-500/5 border border-accent-100 rounded-2xl p-5 flex items-start gap-4 overflow-hidden">
            <span className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-accent-400 via-accent-500 to-brand-400 animate-pulse" />
            <div className="relative shrink-0 mt-0.5">
              <Loader2 size={22} className="animate-spin text-accent-600" />
              <span className="absolute inset-0 rounded-full bg-accent-400/30 animate-pulse-ring" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-accent-800">{t("ai.analysingFor", { q: query })}</p>
              <p className="text-xs text-accent-600 mt-1">{t("ai.fetchHint")}</p>
            </div>
          </div>
          <div className="bg-white border border-slate-200 rounded-2xl p-5 space-y-3">
            <div className="skeleton h-3 rounded w-3/4" />
            <div className="skeleton h-3 rounded w-full" />
            <div className="skeleton h-3 rounded w-5/6" />
            <div className="pt-2 space-y-2">
              <div className="skeleton h-2.5 rounded w-2/3" />
              <div className="skeleton h-2.5 rounded w-1/2" />
              <div className="skeleton h-2.5 rounded w-3/5" />
            </div>
          </div>
        </div>
      )}

      {/* Error */}
      {!!error && !isFetching && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
          {(error as { response?: { data?: { detail?: string } } }).response?.data?.detail
            || t("ai.error")}
        </div>
      )}

      {/* AI Answer */}
      {data && !isFetching && (
        <div className="space-y-4 animate-fade-up">
          {/* Answer card */}
          <div className="relative bg-white border border-slate-200 rounded-2xl shadow-elevated overflow-hidden">
            <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-accent-500 via-brand-500 to-accent-500" />
            <div className="p-6 space-y-4">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center justify-center w-6 h-6 rounded-md bg-gradient-to-br from-accent-500 to-accent-600 shadow-soft">
                    <Sparkles size={13} className="text-white" />
                  </span>
                  <span className="text-sm font-semibold text-slate-800">{t("ai.overview")}</span>
                  <span className="text-xs text-slate-400">· {data.elapsed_ms}ms · {data.model}</span>
                </div>
                <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${overallSentimentClass}`}>
                  {data.sentiment_summary} {t("ai.sentimentSuffix")}
                </span>
              </div>

            {data.expanded_terms?.length > 1 && (
              <ExpandedTermsRow
                original={data.query}
                terms={data.expanded_terms}
                onSelect={(t) => runQuery(t)}
              />
            )}

            <p className="text-sm text-gray-700 leading-relaxed">
              {renderWithCitations(data.answer, sourceCount, cite)}
            </p>

            {data.key_points.length > 0 && (
              <ul className="space-y-2">
                {data.key_points.map((point, i) => (
                  <li key={i} className="flex items-start gap-2.5 text-sm text-gray-700">
                    <CheckCircle2 size={15} className="text-violet-500 shrink-0 mt-0.5" />
                    <span>{renderWithCitations(point, sourceCount, cite)}</span>
                  </li>
                ))}
              </ul>
            )}

              <div className="flex items-start gap-2 pt-3 border-t border-slate-100">
                <Info size={13} className="text-slate-400 shrink-0 mt-0.5" />
                <p className="text-xs text-slate-400">{data.disclaimer}</p>
              </div>
            </div>
          </div>

          {/* Sources — numbered to match [n] citations in the answer above */}
          {data.sources.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                {t("ai.sourcesHeader")} <span className="text-gray-400 normal-case font-normal">— {t("ai.sourcesHint")}</span>
              </p>
              {data.sources.map((s, i) => {
                const isHighlighted = highlightIdx === i;
                return (
                  <div
                    key={i}
                    ref={(el) => { sourceRefs.current[i] = el; }}
                    className={`bg-white border rounded-xl p-3.5 flex items-start gap-3 transition-all duration-300 lift ${isHighlighted ? "border-accent-400 ring-2 ring-accent-200 shadow-elevated" : "border-slate-200"}`}
                  >
                    <span className="shrink-0 w-7 h-7 inline-flex items-center justify-center text-xs font-bold text-white bg-gradient-to-br from-accent-500 to-accent-600 rounded-lg shadow-soft">
                      {i + 1}
                    </span>
                    <div className="flex-1 min-w-0 space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded font-medium capitalize">
                          {SOURCE_ICON[s.source_type] ?? s.source_type}
                        </span>
                        {s.country && (
                          <span className="text-xs text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded">{s.country}</span>
                        )}
                        <SentimentBadge value={s.sentiment} />
                        {s.published_at && (
                          <span className="text-xs text-gray-400 ml-auto">
                            {new Date(s.published_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-600 line-clamp-2">{s.text}</p>
                      {s.source_url && (
                        <a
                          href={s.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-violet-600 hover:underline"
                        >
                          <ExternalLink size={10} /> {t("ai.viewSource")}
                        </a>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!data && !isFetching && !error && (
        <div className="text-center py-20 text-gray-400 space-y-3">
          <Sparkles size={40} className="mx-auto opacity-20 text-violet-400" />
          <p className="text-sm font-medium text-gray-500">{t("ai.empty.title")}</p>
          <p className="text-xs text-gray-300 max-w-sm mx-auto">{t("ai.empty.subtitle")}</p>
          <div className="flex flex-wrap justify-center gap-2 pt-2">
            {[
              "ibuprofen side effects France",
              "Dafalgan availability Belgium",
              "doliprane paediatric dosage",
            ].map((q) => (
              <button
                key={q}
                onClick={() => runQuery(q)}
                className="text-xs px-3 py-1.5 rounded-full border border-violet-200 text-violet-600 hover:bg-violet-50 transition-colors"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Live Search panel ─────────────────────────────────────────────────────────

function LiveSearchPanel({ role }: { role: Role }) {
  const { t } = useI18n();
  const _saved = loadSaved();
  const [query, setQuery] = useState<string>(_saved.query ?? "");
  const [submitted, setSubmitted] = useState<string>(_saved.submitted ?? "");
  const [sources, setSources] = useState<string[]>(_saved.sources ?? ["news", "rss", "wikipedia", "pubmed"]);
  const [filterSentiment, setFilterSentiment] = useState<string>(_saved.filterSentiment ?? "");
  const [period, setPeriod] = useState<string>(_saved.period ?? "all");
  const [showFilters, setShowFilters] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();

  // Honour a `?q=` deep-link (e.g. "Review brand risk", "Full search" buttons):
  // pre-fill + run the search, optionally focusing the risk view with `?risk=1`,
  // then clear the params so a later manual search isn't overridden.
  useEffect(() => {
    const urlQ = (searchParams.get("q") ?? "").trim();
    if (urlQ.length >= 2) {
      setQuery(urlQ);
      setSubmitted(urlQ);
      pushRecent(urlQ);
      if (searchParams.get("risk") === "1") setFilterSentiment("negative");
      setSearchParams({}, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ query, submitted, sources, filterSentiment, period }));
    } catch {}
  }, [query, submitted, sources, filterSentiment, period]);

  const { data, isFetching, error } = useQuery<LiveResponse>({
    queryKey: ["live-search", submitted, sources.join(","), period, role],
    queryFn: () =>
      apiClient
        .get("/search/live", {
          params: { q: submitted, sources: sources.join(","), period, role },
          timeout: 30_000,
        })
        .then((r) => r.data),
    enabled: submitted.length >= 2,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (q.length < 2) return;
    setSubmitted(q);
    pushRecent(q);
  };

  const pickRecent = (q: string) => {
    setQuery(q);
    setSubmitted(q);
    pushRecent(q);
  };

  const toggleSource = (s: string) =>
    setSources((prev) => prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]);

  const displayResults = filterSentiment
    ? (data?.results ?? []).filter((r) => r.sentiment === filterSentiment)
    : (data?.results ?? []);

  const total = data?.total ?? 0;
  const riskCount = (data?.results ?? []).filter((r) => r.is_risk).length;

  return (
    <div className="space-y-5 pt-1">
      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="relative flex-1 group">
          <SearchIcon size={17} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-brand-500 transition-colors" />
          <input
            type="text"
            data-search-input="live"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("live.placeholder")}
            className="w-full pl-10 pr-4 py-3 bg-white border border-slate-200 rounded-xl text-sm shadow-soft focus:outline-none focus:border-brand-400 focus:shadow-ring-brand transition-shadow"
            autoFocus
          />
        </div>
        <button
          type="button"
          onClick={() => setShowFilters((f) => !f)}
          className={`flex items-center gap-1.5 px-4 py-3 border rounded-xl text-sm font-medium transition-colors shadow-soft ${showFilters ? "border-brand-300 text-brand-700 bg-brand-50" : "bg-white border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50"}`}
        >
          <Filter size={15} /> {t("live.filters")}
        </button>
        <button
          type="submit"
          disabled={query.trim().length < 2 || isFetching}
          className="flex items-center gap-2 px-6 py-3 text-white text-sm font-semibold rounded-xl shadow-elevated bg-gradient-to-br from-brand-500 to-brand-600 hover:from-brand-600 hover:to-brand-700 transition-all disabled:opacity-50 disabled:cursor-not-allowed disabled:from-slate-400 disabled:to-slate-500"
        >
          {isFetching ? <Loader2 size={15} className="animate-spin" /> : <SearchIcon size={15} />}
          {isFetching ? t("live.searching") : t("live.search")}
        </button>
      </form>

      <RecentSearches onPick={pickRecent} />

      {showFilters && (
        <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-4">
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 flex items-center gap-1.5">
              <Clock size={12} /> {t("filter.period")}
            </p>
            <div className="flex gap-2 flex-wrap">
              {PERIOD_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setPeriod(opt.value)}
                  className={`px-3 py-1 rounded-lg text-xs font-medium border transition-colors ${period === opt.value ? "bg-blue-600 text-white border-blue-600" : "bg-white text-gray-600 border-gray-300 hover:border-blue-400"}`}
                >
                  {t(opt.tKey)}
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">{t("filter.sources")}</p>
            <div className="flex gap-2 flex-wrap">
              {LIVE_SOURCES.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => toggleSource(s)}
                  className={`px-3 py-1 rounded-lg text-xs font-medium border transition-colors ${sources.includes(s) ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-gray-600 border-gray-300 hover:border-indigo-400"}`}
                >
                  {SOURCE_ICON[s] ?? s}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {isFetching && (
        <div className="space-y-3">
          <div className="relative bg-gradient-to-br from-brand-500/10 via-transparent to-brand-500/5 border border-brand-100 rounded-2xl p-4 flex items-center gap-3 overflow-hidden">
            <span className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-brand-400 via-brand-500 to-accent-400 animate-pulse" />
            <Loader2 size={20} className="animate-spin text-brand-600 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-brand-800">{t("live.loading.title")}</p>
              <p className="text-xs text-brand-600 mt-0.5">
                {sources.join(", ")} · {t(PERIOD_OPTIONS.find((p) => p.value === period)?.tKey ?? "period.all")} — {t("live.loading.hint")}
              </p>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {[0,1,2,3].map((i) => (
              <div key={i} className="bg-white border border-slate-200 rounded-xl p-3.5 h-[178px] flex flex-col gap-2">
                <div className="skeleton h-2.5 rounded w-1/2" />
                <div className="skeleton flex-1 rounded" />
              </div>
            ))}
          </div>
        </div>
      )}

      {error && !isFetching && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
          {t("live.error")}
        </div>
      )}

      {data && !isFetching && (
        <>
          {/* Results header: stat block on left, primary action + risk pill on right */}
          <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
            <div className="min-w-0">
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="text-3xl font-bold text-slate-900 tabular-nums leading-none">{total}</span>
                <span className="text-sm font-medium text-slate-700">
                  {total === 1 ? t("results.countLabel.one") : t("results.countLabel")}
                </span>
                <span className="text-brand-700 font-semibold text-sm truncate max-w-xs">"{data.query}"</span>
              </div>
              <p className="text-xs text-slate-400 mt-1.5">
                {t("results.via")} {data.sources_queried.join(", ")} · {t(PERIOD_OPTIONS.find((p) => p.value === period)?.tKey ?? "period.all")} · {data.elapsed_ms}ms
              </p>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              {riskCount > 0 && (
                <span className="flex items-center gap-1.5 text-xs text-red-700 bg-red-50 border border-red-200 px-2.5 py-1.5 rounded-lg font-medium">
                  <AlertTriangle size={12} />
                  {riskCount} {riskCount === 1 ? t("risk.flagsShort.one") : t("risk.flagsShort")}
                </span>
              )}
            </div>
          </div>

          {/* Sentiment filter — its own segmented control row */}
          {total > 0 && (
            <div className="inline-flex items-center bg-white border border-slate-200 rounded-lg p-1 shadow-soft">
              <button
                onClick={() => setFilterSentiment("")}
                className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${!filterSentiment ? "bg-slate-900 text-white shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
              >
                {t("sentiment.all")}
              </button>
              {SENTIMENTS.map((s) => (
                <button
                  key={s}
                  onClick={() => setFilterSentiment(filterSentiment === s ? "" : s)}
                  className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${filterSentiment === s ? SENTIMENT_STYLE[s] + " shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
                >
                  {t(`sentiment.${s}`)}
                </button>
              ))}
            </div>
          )}

          {data.expanded_terms?.length > 1 && (
            <ExpandedTermsRow
              original={data.query}
              terms={data.expanded_terms}
              onSelect={pickRecent}
            />
          )}

          {total > 0 && data.metrics && <InsightPanel intel={data.metrics} />}

          <YouTubeAnalyticsPanel results={data.results} />

          <RiskCallout results={(data?.results ?? []).filter((r) => r.is_risk)} query={data?.query ?? submitted} />

          {data.source_notices && data.source_notices.length > 0 && (
            <SourceNoticesBanner notices={data.source_notices} />
          )}

          {/* Sentiment filter is on but it hid every row — keep search visible
              by explaining why the list is empty instead of going silent. */}
          {total > 0 && displayResults.length === 0 && filterSentiment && (
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 flex items-start gap-3 text-sm">
              <Filter size={15} className="text-slate-500 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-slate-700 font-medium">
                  No <span className="capitalize">{filterSentiment}</span> results — but the search returned <span className="font-semibold">{total}</span> total.
                </p>
                <button
                  type="button"
                  onClick={() => setFilterSentiment("")}
                  className="mt-1 text-xs text-brand-600 hover:text-brand-800 hover:underline"
                >
                  Clear the {filterSentiment} filter to see all results.
                </button>
              </div>
            </div>
          )}

          {displayResults.length === 0 && total === 0 && (
            <div className="text-center py-12 text-gray-500 text-sm space-y-3">
              <Globe size={32} className="mx-auto opacity-30 text-gray-400" />
              <p>{t("noResults.headline")} <span className="font-semibold text-gray-700">"{data.query}"</span> {t("noResults.acrossSources")}</p>
              {data.expanded_terms.filter((x) => x.toLowerCase() !== data.query.trim().toLowerCase()).length > 0 ? (
                <div className="space-y-2">
                  <p className="text-xs text-gray-400">{t("noResults.tryVariants")}</p>
                  <div className="flex flex-wrap justify-center gap-2">
                    {data.expanded_terms
                      .filter((x) => x.toLowerCase() !== data.query.trim().toLowerCase())
                      .map((term) => (
                        <button
                          key={term}
                          type="button"
                          onClick={() => pickRecent(term)}
                          className="text-xs px-3 py-1.5 rounded-full border border-indigo-200 text-indigo-700 bg-indigo-50 hover:bg-indigo-100 hover:border-indigo-400 transition-colors"
                        >
                          {term}
                        </button>
                      ))}
                  </div>
                </div>
              ) : (
                <p className="text-xs text-gray-400">
                  {t("noResults.tryName")}{" "}
                  {["paracetamol", "ibuprofen", "Doliprane", "Dafalgan"].map((term, i, arr) => (
                    <span key={term}>
                      <button
                        type="button"
                        onClick={() => pickRecent(term)}
                        className="text-indigo-600 hover:text-indigo-800 hover:underline font-medium"
                      >
                        {term}
                      </button>
                      {i < arr.length - 1 ? ", " : ""}
                    </span>
                  ))}
                  . {t("noResults.widenFilters")}
                </p>
              )}
            </div>
          )}

          <div className="space-y-3">
            {displayResults.map((r, i) => {
              const accentClass = r.is_risk
                ? "accent-risk"
                : r.sentiment === "positive"
                ? "accent-positive"
                : r.sentiment === "negative"
                ? "accent-negative"
                : "accent-neutral";
              return (
                <div
                  key={i}
                  className={`relative bg-white rounded-xl border border-slate-200 pl-5 pr-4 py-4 space-y-2.5 lift ${accentClass} ${r.is_risk ? "bg-red-50/20" : ""}`}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs bg-slate-100 text-slate-700 px-2 py-0.5 rounded font-medium">
                      {SOURCE_ICON[r.source_type] ?? r.source_type}
                    </span>
                    {r.country && (
                      <span className="text-xs bg-brand-50 text-brand-700 px-2 py-0.5 rounded font-medium">{r.country}</span>
                    )}
                    {r.language && (
                      <span className="text-[10px] tracking-wider uppercase bg-slate-50 text-slate-500 px-1.5 py-0.5 rounded font-semibold">{r.language}</span>
                    )}
                    <SentimentBadge value={r.sentiment} />
                    {r.topic && r.topic !== "general" && (
                      <span className="text-xs bg-brand-50 text-brand-700 px-2 py-0.5 rounded-full font-medium capitalize">
                        {r.topic.replace("_", " ")}
                      </span>
                    )}
                    {r.is_risk && (
                      <span className="flex items-center gap-1 text-xs text-red-700 bg-red-50 border border-red-200 px-2 py-0.5 rounded-full font-medium">
                        <AlertTriangle size={11} /> {r.risk_type.replace("_", " ")}
                      </span>
                    )}
                    {r.engagement != null && r.engagement > 0 && (
                      <span className="text-xs text-slate-400 ml-1">↑ {r.engagement}</span>
                    )}
                    <span className="ml-auto text-xs text-slate-400">
                      {r.published_at
                        ? new Date(r.published_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })
                        : ""}
                    </span>
                  </div>
                  {r.source_type === "youtube" && r.meta ? (
                    <div className="flex gap-3">
                      {r.meta.thumbnail && (
                        <a href={r.source_url} target="_blank" rel="noopener noreferrer" className="shrink-0">
                          <img src={r.meta.thumbnail} alt="" loading="lazy" className="w-28 h-[63px] rounded-lg object-cover bg-slate-100" />
                        </a>
                      )}
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-slate-700 leading-relaxed line-clamp-2">{r.meta.title || r.text}</p>
                        {r.meta.channel_title && (
                          <p className="text-xs text-slate-400 mt-0.5 truncate">{r.meta.channel_title}</p>
                        )}
                        <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-500">
                          <span className="flex items-center gap-1"><Eye size={12} className="text-red-500" /> {formatCompact(r.meta.views)}</span>
                          <span className="flex items-center gap-1"><ThumbsUp size={12} /> {formatCompact(r.meta.likes)}</span>
                          <span className="flex items-center gap-1"><MessageSquare size={12} /> {formatCompact(r.meta.comments)}</span>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <p className="text-sm text-slate-700 leading-relaxed">{r.text}</p>
                  )}
                  {r.source_url && (
                    <a
                      href={r.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-brand-600 hover:text-brand-800 hover:underline font-medium"
                    >
                      <ExternalLink size={11} /> {r.source_type === "youtube" ? t("yt.watch") : "View original source"}
                    </a>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {!submitted && !isFetching && (
        <div className="text-center py-20 text-gray-400 space-y-3">
          <Rss size={40} className="mx-auto opacity-20" />
          <p className="text-sm font-medium text-gray-500">{t("live.empty.title")}</p>
          <p className="text-xs text-gray-300 max-w-sm mx-auto">{t("live.empty.subtitle")}</p>
          <div className="flex flex-wrap justify-center gap-2 pt-2">
            {["paracetamol", "ibuprofen", "Doliprane", "Dafalgan"].map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => pickRecent(q)}
                className="text-xs px-3 py-1.5 rounded-full border border-blue-200 text-blue-600 hover:bg-blue-50 transition-colors"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Search() {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState<Tab>("search");

  // The lens follows the logged-in account role. Admins may additionally "view
  // as" any persona (persisted), so one account can demo all three. Non-admins
  // are pinned to their own role — the backend enforces this regardless.
  const [loggedInRole] = useState<Role>(getLoggedInRole);
  const isAdmin = loggedInRole === "admin";
  const [lensRole, setLensRole] = useState<Role>(() => {
    if (!isAdmin) return loggedInRole;
    try {
      const s = localStorage.getItem(LENS_STORAGE_KEY);
      if (isRole(s)) return s;
    } catch {}
    return "admin";
  });
  const changeLens = (r: Role) => {
    setLensRole(r);
    try { localStorage.setItem(LENS_STORAGE_KEY, r); } catch {}
  };

  // ⌘K / Ctrl+K focuses the active tab's search input
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        const which = activeTab === "ai" ? "ai" : "live";
        const el = document.querySelector<HTMLInputElement>(`input[data-search-input="${which}"]`);
        if (el) {
          el.focus();
          el.select();
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [activeTab]);

  // Keep panels mounted so neither loses internal state when switching tabs
  return (
    <div className="space-y-0 max-w-5xl animate-fade-up">
      {/* Hero header — clean white banner to match the white rail */}
      <div className="relative mb-6 rounded-2xl overflow-hidden bg-white shadow-soft ring-1 ring-slate-200">
        <span className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-brand-400 via-accent-400 to-brand-400" />
        <div className="absolute inset-0 bg-grid-soft opacity-[0.05] pointer-events-none [mask-image:radial-gradient(ellipse_at_top_right,black_10%,transparent_65%)]" />
        <div className="absolute -right-16 -top-20 w-72 h-72 rounded-full bg-brand-500/10 blur-3xl pointer-events-none" />
        <div className="relative px-6 py-5 flex items-start gap-4">
          <div className="shrink-0 w-11 h-11 rounded-xl bg-gradient-to-br from-brand-500 to-accent-500 flex items-center justify-center shadow-elevated ring-1 ring-black/5">
            <SearchIcon size={20} className="text-white" strokeWidth={2.4} />
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">{t("page.title")}</h1>
            <p className="text-sm text-slate-500 mt-0.5 max-w-2xl">{t("page.subtitle")}</p>
          </div>
          {isAdmin && (
            <div className="shrink-0 self-center hidden sm:block">
              <RoleSwitcher value={lensRole} onChange={changeLens} />
            </div>
          )}
        </div>
      </div>

      {/* Active role lens — what this query is being tailored toward */}
      <div className="mb-6 space-y-2">
        <LensBanner role={lensRole} />
        {isAdmin && (
          <div className="sm:hidden">
            <RoleSwitcher value={lensRole} onChange={changeLens} />
          </div>
        )}
      </div>

      <div className="flex gap-1 border-b border-slate-200 mb-8">
        <button
          onClick={() => setActiveTab("search")}
          className={`relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-all -mb-px ${
            activeTab === "search"
              ? "text-brand-700"
              : "text-slate-500 hover:text-slate-800"
          }`}
        >
          <SearchIcon size={15} />
          {t("tab.search")}
          {activeTab === "search" && (
            <span className="absolute left-2 right-2 -bottom-px h-0.5 rounded-full bg-gradient-to-r from-brand-500 to-brand-600" />
          )}
        </button>
        <button
          onClick={() => setActiveTab("ai")}
          className={`relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-all -mb-px ${
            activeTab === "ai"
              ? "text-accent-700"
              : "text-slate-500 hover:text-slate-800"
          }`}
        >
          <Sparkles size={15} />
          {t("tab.ai")}
          {activeTab === "ai" && (
            <span className="absolute left-2 right-2 -bottom-px h-0.5 rounded-full bg-gradient-to-r from-accent-500 to-accent-600" />
          )}
        </button>
        <span className="ml-auto self-center hidden md:inline-flex items-center gap-1.5 text-[11px] text-slate-400">
          <kbd className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-slate-200 bg-white text-slate-500 font-medium shadow-sm">
            <Command size={10} />K
          </kbd>
          {t("shortcut.focus")}
        </span>
      </div>

      <div className={activeTab === "search" ? "" : "hidden"}>
        <LiveSearchPanel role={lensRole} />
      </div>
      <div className={activeTab === "ai" ? "" : "hidden"}>
        <AIModePanel role={lensRole} />
      </div>
    </div>
  );
}
