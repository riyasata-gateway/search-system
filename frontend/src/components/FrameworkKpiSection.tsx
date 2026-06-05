import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { Activity, Lock, BarChart3, Lightbulb, Trophy, Sparkles, ChevronDown, ChevronUp } from "lucide-react";
import InfoTip from "./InfoTip";

/**
 * Role-scoped performance KPIs for one brand.
 *
 * Renders the per-role KPI set against the selected brand: each live/partial KPI
 * shows a real value computed from the ingested corpus, while not-yet-connected
 * KPIs show a "Connect feed" badge instead of a fabricated number. Share-of-voice
 * KPIs also list the category peers so the share is read in context, and the
 * section leads with an auto-generated "What this means" interpretation.
 * Driven by GET /catalog/brand-kpis.
 *
 * Styling note: the app runs on the dark "Command Center" canvas. We style the
 * new bits with explicit translucent-white fills (bg-white/[…]) rather than
 * light gray utilities, because the global dark reskin only rewrites the plain
 * gray classes — opacity-modified ones slip through and render light-on-dark.
 */

type Peer = { name: string; share: number; is_self: boolean };

type Kpi = {
  key: string;
  kpi: string;
  logic: string;
  importance?: string;
  metric_type: string;
  data_sources: string[];
  dia_layer: string;
  data_status: "live" | "partial" | "data_needed";
  value: number | null;
  display: string;
  detail: string | null;
  peers?: Peer[];
  peers_label?: string;
  rank?: number;
  peer_count?: number;
};

type BrandKpis = {
  role: string;
  brand: { id: number; name: string; category: string | null };
  kpis: Kpi[];
  insights: string[];
};

const STATUS: Record<string, { label: string; chip: string; dot: string }> = {
  live: { label: "Live", chip: "bg-emerald-500/15 text-emerald-300 border-emerald-400/30", dot: "bg-emerald-400" },
  partial: { label: "Partial", chip: "bg-amber-500/15 text-amber-300 border-amber-400/30", dot: "bg-amber-400" },
  data_needed: { label: "Connect feed", chip: "bg-white/10 text-slate-400 border-white/15", dot: "bg-slate-500" },
};

function cap(s?: string) {
  return s ? s.replace("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "";
}

function PeerList({ peers, label }: { peers: Peer[]; label?: string }) {
  return (
    <div className="mt-2.5 space-y-1">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label ?? "Category mix"}</p>
      {peers.slice(0, 6).map((p, i) => (
        <div key={p.name} className="flex items-center gap-2 text-[11px]">
          <span className={`w-4 text-right tabular-nums ${p.is_self ? "text-white" : "text-slate-500"}`}>{i + 1}.</span>
          <span className={`flex-1 truncate ${p.is_self ? "text-white font-semibold" : "text-slate-400"}`}>{p.name}</span>
          <div className="w-16 h-1.5 rounded-full bg-white/10 overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${p.share}%`, background: p.is_self ? "#8aa6ff" : "rgba(148,163,184,0.5)" }} />
          </div>
          <span className={`w-8 text-right tabular-nums ${p.is_self ? "text-white font-semibold" : "text-slate-500"}`}>{p.share}%</span>
        </div>
      ))}
      {peers.length > 6 && <p className="text-[10px] text-slate-500 pl-6">+{peers.length - 6} more</p>}
    </div>
  );
}

function KpiCard({ k }: { k: Kpi }) {
  const s = STATUS[k.data_status] ?? STATUS.data_needed;
  const isDataNeeded = k.data_status === "data_needed";
  return (
    <div className={`rounded-xl border p-4 flex flex-col ${isDataNeeded ? "border-dashed border-white/15 bg-white/[0.02]" : "border-white/10 bg-white/[0.04]"}`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="text-sm font-medium text-slate-200 leading-snug flex items-center gap-1.5">
          {k.kpi}
          <InfoTip text={k.importance || k.logic} label={k.kpi} />
        </span>
        <span className={`shrink-0 inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${s.chip}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} /> {s.label}
        </span>
      </div>
      <p className={`text-2xl font-bold tabular-nums ${isDataNeeded ? "text-slate-600" : "text-white"}`}>
        {isDataNeeded
          ? <span className="inline-flex items-center gap-1.5 text-base font-semibold text-slate-400"><Lock size={14} /> Connect feed</span>
          : k.display}
      </p>
      {k.detail && !isDataNeeded && <p className="text-xs text-slate-400 mt-0.5">{k.detail}</p>}
      {isDataNeeded && k.data_sources?.length > 0 && (
        <p className="text-[11px] text-slate-500 mt-1">
          Needs: <span className="text-slate-400">{k.data_sources.join(" · ")}</span>
        </p>
      )}
      {k.peers && k.peers.length > 0 && <PeerList peers={k.peers} label={k.peers_label} />}
      <span className="mt-auto pt-3 text-[10px] text-slate-500 uppercase tracking-wide">{k.dia_layer}</span>
    </div>
  );
}

export default function FrameworkKpiSection({
  brandId,
  role,
  excludeKeys,
}: {
  brandId: number | null;
  /** Pass only for admins viewing-as a role; non-admins are locked server-side. */
  role?: string;
  /** KPI keys already shown elsewhere on the page (e.g. the Brand Pulse headline
   * panels) — excluded here so the same metric isn't rendered twice. */
  excludeKeys?: string[];
}) {
  const [showUpgrade, setShowUpgrade] = useState(false);
  const [showEmpty, setShowEmpty] = useState(false);
  const { data, isLoading } = useQuery<BrandKpis>({
    queryKey: ["brand-kpis", brandId, role],
    queryFn: () =>
      apiClient
        .get("/catalog/brand-kpis", { params: { brand_id: brandId, ...(role ? { role } : {}) } })
        .then((r) => r.data),
    enabled: brandId != null,
  });

  if (brandId == null) return null;

  const kpis = (data?.kpis ?? []).filter((k) => !excludeKeys?.includes(k.key));
  const insights = data?.insights ?? [];
  // A KPI is "not available for this brand" when it has no value to show — either
  // it doesn't apply (e.g. a medicine-only KPI for a cosmetic) or there's no
  // source data for this brand yet. We collapse these so the real KPIs lead
  // instead of a wall of "Insufficient data" cards.
  const EMPTY_DISPLAYS = new Set(["Insufficient data", "n/a", "N/A", "—", "None", ""]);
  const isEmpty = (k: Kpi) => k.value == null && EMPTY_DISPLAYS.has((k.display || "").trim());

  // Live KPIs (with a real value) lead; external-feed KPIs (IQVIA / sell-out /
  // wholesaler / loyalty) are gated behind the Upgrade button; not-available
  // KPIs collapse into their own muted section.
  const lockedKpis = kpis.filter((k) => k.data_status === "data_needed");
  const liveKpis = kpis.filter((k) => k.data_status !== "data_needed" && !isEmpty(k));
  const emptyKpis = kpis.filter((k) => k.data_status !== "data_needed" && isEmpty(k));
  const lockedFeeds = Array.from(
    new Set(lockedKpis.flatMap((k) => k.data_sources ?? [])),
  );
  const title = data?.role && data.role !== "admin" ? `${cap(data.role)} KPIs` : "Performance KPIs";

  return (
    <div className="bg-white rounded-xl border border-gray-200">
      <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2">
            <BarChart3 size={16} className="text-indigo-500" />
            {title}
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            The indicators that drive your decisions for {data?.brand?.name ?? "this brand"}
            {data?.brand?.category ? ` · ${data.brand.category}` : ""}.
          </p>
        </div>
        {kpis.length > 0 && (
          <span className="text-xs text-gray-400 flex items-center gap-1.5">
            <Activity size={13} className="text-green-500" />
            {liveKpis.length} live
            {emptyKpis.length > 0 ? ` · ${emptyKpis.length} n/a` : ""}
            {lockedKpis.length > 0 ? ` · ${lockedKpis.length} premium` : ""}
          </span>
        )}
      </div>

      <div className="p-5 space-y-5">
        {/* Auto-generated interpretation of the live KPIs */}
        {insights.length > 0 && (
          <div className="rounded-xl border border-amber-400/25 bg-amber-500/[0.07] p-4">
            <h3 className="text-sm font-semibold text-amber-200 flex items-center gap-1.5 mb-2">
              <Lightbulb size={14} /> What this means
            </h3>
            <ul className="space-y-1.5">
              {insights.map((t, i) => (
                <li key={i} className="text-[13px] text-slate-300 leading-snug flex gap-2">
                  <Trophy size={12} className="mt-0.5 shrink-0 text-amber-300/70" />
                  <span>{t}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {isLoading ? (
          <p className="text-sm text-gray-400">Loading KPIs…</p>
        ) : kpis.length === 0 ? (
          <p className="text-sm text-gray-400">No KPIs defined for this role.</p>
        ) : (
          <>
            {liveKpis.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {liveKpis.map((k) => <KpiCard key={k.key} k={k} />)}
              </div>
            ) : (
              <p className="text-sm text-slate-400">
                No live KPIs for {data?.brand?.name ?? "this brand"} yet — it has little ingested data so far
                (see the {emptyKpis.length} not-available indicator{emptyKpis.length === 1 ? "" : "s"} below for why).
              </p>
            )}

            {/* Not available for this brand — n/a or no source data yet (collapsed) */}
            {emptyKpis.length > 0 && (
              <div className="rounded-xl border border-white/10 bg-white/[0.02]">
                <button
                  type="button"
                  onClick={() => setShowEmpty((v) => !v)}
                  className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left"
                >
                  <span className="text-sm font-medium text-slate-400">
                    {emptyKpis.length} indicator{emptyKpis.length === 1 ? "" : "s"} not available for {data?.brand?.name ?? "this brand"}
                  </span>
                  <span className="shrink-0 inline-flex items-center gap-1 text-xs font-medium text-slate-400">
                    {showEmpty ? "Hide" : "Show"}
                    {showEmpty ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                  </span>
                </button>
                {showEmpty && (
                  <div className="px-4 pb-4 pt-1 space-y-3">
                    <p className="text-[11px] text-slate-500 leading-relaxed">
                      These don't apply to this brand (e.g. medicine-only metrics for a cosmetic/supplement) or have
                      no ingested source data for it yet — shown as "n/a"/"Insufficient data" rather than a fabricated number.
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                      {emptyKpis.map((k) => <KpiCard key={k.key} k={k} />)}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Upgrade — external-feed KPIs (IQVIA / sell-out / wholesaler / loyalty) */}
            {lockedKpis.length > 0 && (
              <div className="rounded-xl border border-accent-400/30 bg-accent-500/[0.07]">
                <button
                  type="button"
                  onClick={() => setShowUpgrade((v) => !v)}
                  className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left"
                >
                  <span className="flex items-center gap-2.5 min-w-0">
                    <span className="shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-accent-500 to-accent-600 flex items-center justify-center shadow-soft">
                      <Sparkles size={16} className="text-white" />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-semibold text-slate-100">
                        Upgrade — unlock {lockedKpis.length} premium KPI{lockedKpis.length === 1 ? "" : "s"}
                      </span>
                      <span className="block text-[11px] text-slate-400 truncate">
                        Connect {lockedFeeds.slice(0, 3).join(" · ")}
                        {lockedFeeds.length > 3 ? ` +${lockedFeeds.length - 3} more` : ""}
                      </span>
                    </span>
                  </span>
                  <span className="shrink-0 inline-flex items-center gap-1 text-xs font-semibold text-accent-200">
                    {showUpgrade ? "Hide" : "Preview"}
                    {showUpgrade ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                  </span>
                </button>

                {showUpgrade && (
                  <div className="px-4 pb-4 pt-1 space-y-3">
                    <p className="text-[11px] text-slate-400 leading-relaxed">
                      These decisions need transacted sales or a paid market panel — they
                      stay locked until the feed is connected. The live KPIs above are the
                      public-signal proxies that approximate them today.
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                      {lockedKpis.map((k) => <KpiCard key={k.key} k={k} />)}
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
