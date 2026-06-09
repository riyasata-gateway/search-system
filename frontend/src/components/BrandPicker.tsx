import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import {
  Search, ChevronLeft, ChevronRight, ChevronDown, Pill, CircleDot,
  CircleDashed, Loader2, Check,
} from "lucide-react";
import clsx from "clsx";
import { useTheme } from "../lib/theme";

/**
 * BrandPicker — pick any of the ~2k classified brands, organised by the 5-code
 * primary category.
 *
 * Replaces the flat "my brands" <select> on the role dashboards. The trigger
 * shows the current brand; opening it reveals the five categories (each with the
 * total number of brands it holds in parentheses) plus an "All" chip. Selecting a
 * category lists that category's brands; selecting a brand drives the dashboard's
 * KPIs. Search spans every category. Backed by GET /catalog/brand-catalog.
 */

export type PickerBrand = {
  id: number;
  name: string;
  primary_category: string;
  category: string | null;
  manufacturer: string | null;
  has_data: boolean;
  is_medicine: boolean;
};

type Category = { code: string; label_fr: string; label_en: string; definition: string; count: number };
type CatalogResponse = {
  categories: Category[]; total_all: number; total: number; page: number;
  page_size: number; category: string | null; q: string | null; brands: PickerBrand[];
};

type CatTints = { chip: string; active: string; badge: string };

// Per-category tints — dark-canvas variant + a light variant, picked by theme.
const CAT_STYLE_DARK: Record<string, CatTints> = {
  NUT: { chip: "border-emerald-400/30 text-emerald-300", active: "bg-emerald-500/20 ring-emerald-400/50", badge: "bg-emerald-500/15 text-emerald-300 border-emerald-400/30" },
  RX:  { chip: "border-sky-400/30 text-sky-300",         active: "bg-sky-500/20 ring-sky-400/50",         badge: "bg-sky-500/15 text-sky-300 border-sky-400/30" },
  PAC: { chip: "border-violet-400/30 text-violet-300",   active: "bg-violet-500/20 ring-violet-400/50",   badge: "bg-violet-500/15 text-violet-300 border-violet-400/30" },
  PEC: { chip: "border-amber-400/30 text-amber-300",     active: "bg-amber-500/20 ring-amber-400/50",     badge: "bg-amber-500/15 text-amber-300 border-amber-400/30" },
  OTC: { chip: "border-cyan-400/30 text-cyan-300",       active: "bg-cyan-500/20 ring-cyan-400/50",       badge: "bg-cyan-500/15 text-cyan-300 border-cyan-400/30" },
};
const CAT_STYLE_LIGHT: Record<string, CatTints> = {
  NUT: { chip: "border-emerald-300 text-emerald-700", active: "bg-emerald-100 ring-emerald-300", badge: "bg-emerald-100 text-emerald-700 border-emerald-300" },
  RX:  { chip: "border-sky-300 text-sky-700",         active: "bg-sky-100 ring-sky-300",         badge: "bg-sky-100 text-sky-700 border-sky-300" },
  PAC: { chip: "border-violet-300 text-violet-700",   active: "bg-violet-100 ring-violet-300",   badge: "bg-violet-100 text-violet-700 border-violet-300" },
  PEC: { chip: "border-amber-300 text-amber-700",     active: "bg-amber-100 ring-amber-300",     badge: "bg-amber-100 text-amber-700 border-amber-300" },
  OTC: { chip: "border-cyan-300 text-cyan-700",       active: "bg-cyan-100 ring-cyan-300",       badge: "bg-cyan-100 text-cyan-700 border-cyan-300" },
};
const NEUTRAL_DARK  = { chip: "border-white/15 text-slate-300", active: "bg-white/15 ring-white/30",   badge: "bg-white/10 text-slate-300 border-white/15" };
const NEUTRAL_LIGHT = { chip: "border-gray-300 text-gray-600",  active: "bg-gray-200 ring-gray-300",   badge: "bg-gray-100 text-gray-600 border-gray-300" };

const catTints = (code: string, dark: boolean): CatTints =>
  (dark ? CAT_STYLE_DARK : CAT_STYLE_LIGHT)[code] ?? (dark ? NEUTRAL_DARK : NEUTRAL_LIGHT);

export function CatBadge({ code }: { code: string }) {
  const { theme } = useTheme();
  const s = catTints(code, theme === "dark");
  return <span className={clsx("text-[10px] font-semibold px-1.5 py-0.5 rounded border", s.badge)}>{code}</span>;
}

type Props = {
  value: number | null;
  onSelect: (brand: PickerBrand) => void;
  /** The resolved selected brand, held by the parent. Used for the trigger label
   *  so it survives the picker being unmounted (e.g. a parent loading state). */
  selectedBrand?: PickerBrand | null;
  /** Auto-select the first brand (preferring one with data) on first load. */
  autoSelect?: boolean;
};

export default function BrandPicker({ value, onSelect, selectedBrand, autoSelect = true }: Props) {
  const { user } = useAuth();
  const { theme } = useTheme();
  const dark = theme === "dark";
  const neutral = dark ? NEUTRAL_DARK : NEUTRAL_LIGHT;
  // Theme-aware popover chrome (the panel uses an arbitrary hex bg the global
  // reskin can't touch, so the picker themes itself explicitly).
  const ui = dark
    ? {
        panel: "border-white/10 bg-[#0f1626] ring-1 ring-black/40",
        rail: "border-white/10 bg-white/[0.02]",
        activeText: "text-white",
        hover: "hover:bg-white/5",
        search: "border-white/10 bg-white/[0.04] text-slate-100 placeholder:text-slate-500 focus:ring-white/30",
        listBorder: "border-white/5",
        divide: "divide-white/5",
        rowSel: "bg-white/[0.08]",
        rowHover: "hover:bg-white/[0.04]",
        rowText: "text-slate-100",
        pageHover: "hover:bg-white/10",
      }
    : {
        panel: "border-gray-200 bg-white ring-1 ring-black/5",
        rail: "border-gray-200 bg-gray-50",
        activeText: "text-gray-900",
        hover: "hover:bg-gray-100",
        search: "border-gray-300 bg-white text-gray-900 placeholder:text-gray-400 focus:ring-blue-400",
        listBorder: "border-gray-200",
        divide: "divide-gray-100",
        rowSel: "bg-gray-100",
        rowHover: "hover:bg-gray-50",
        rowText: "text-gray-900",
        pageHover: "hover:bg-gray-100",
      };
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState<string | null>(null);
  const [rawQ, setRawQ] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  // Remember the chosen brand so the trigger can label itself without a re-fetch.
  const [selected, setSelected] = useState<PickerBrand | null>(null);
  const pageSize = 50;
  const rootRef = useRef<HTMLDivElement>(null);
  const didAutoSelect = useRef(false);

  // Debounce search so we don't fire a query per keystroke.
  useEffect(() => {
    const t = setTimeout(() => { setQ(rawQ.trim()); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [rawQ]);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const { data, isFetching } = useQuery<CatalogResponse>({
    queryKey: ["brand-picker", q, category, page, user?.role],
    queryFn: () => apiClient.get("/catalog/brand-catalog", {
      params: { ...(q ? { q } : {}), ...(category ? { category } : {}), page, page_size: pageSize },
    }).then((r) => r.data),
    placeholderData: keepPreviousData,
  });

  const categories = data?.categories ?? [];
  const totalAll = data?.total_all ?? 0;
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const brands = data?.brands ?? [];

  const activeDef = useMemo(
    () => categories.find((c) => c.code === category)?.definition,
    [categories, category]
  );

  // First load with no selection → auto-pick a sensible default (a brand that
  // already has linked data, else the first listed).
  useEffect(() => {
    if (!autoSelect || didAutoSelect.current) return;
    if (value != null || selected != null || selectedBrand != null) return;
    if (!brands.length) return;
    const pick = brands.find((b) => b.has_data) ?? brands[0];
    didAutoSelect.current = true;
    setSelected(pick);
    onSelect(pick);
  }, [autoSelect, brands, value, selected, selectedBrand, onSelect]);

  const choose = (b: PickerBrand) => {
    setSelected(b);
    onSelect(b);
    setOpen(false);
  };

  const selectCat = (code: string | null) => { setCategory(code); setPage(1); };

  // Trigger label: prefer the parent-held brand (survives remount), then the
  // locally-chosen one. `value` may match neither yet (still loading).
  const display = selectedBrand ?? selected;
  const selectedId = value ?? display?.id ?? null;

  return (
    <div ref={rootRef} className="relative">
      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 min-w-[15rem] border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white hover:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-400"
      >
        {display ? (
          <>
            <CatBadge code={display.primary_category} />
            <span className="flex-1 min-w-0 truncate text-left text-gray-900">{display.name}</span>
            {!display.has_data && <span className="shrink-0 text-[10px] text-slate-400">no data yet</span>}
          </>
        ) : (
          <span className="flex-1 text-left text-gray-500">Select a brand…</span>
        )}
        <ChevronDown size={16} className="shrink-0 text-gray-400" />
      </button>

      {/* Popover — a two-pane cascade: category rail (left) → its brands (right) */}
      {open && (
        <div className={clsx("absolute right-0 z-30 mt-2 w-[min(94vw,38rem)] rounded-xl border shadow-2xl overflow-hidden", ui.panel)}>
          <div className="flex h-[min(60vh,30rem)]">
            {/* ── Level 1: category rail ─────────────────────────────────── */}
            <div className={clsx("w-[11rem] shrink-0 border-r overflow-y-auto py-1.5", ui.rail)}>
              {(() => {
                const allActive = category === null;
                return (
                  <button
                    type="button"
                    onClick={() => selectCat(null)}
                    className={clsx(
                      "w-full text-left px-3 py-2 flex items-center gap-2 text-xs transition-colors",
                      allActive ? clsx(ui.activeText, neutral.active, "ring-1") : clsx(neutral.chip, ui.hover)
                    )}
                  >
                    <span className="flex-1 font-medium">All brands</span>
                    <span className="opacity-60 tabular-nums">{totalAll.toLocaleString()}</span>
                    <ChevronRight size={13} className={clsx("shrink-0", allActive ? "opacity-80" : "opacity-30")} />
                  </button>
                );
              })()}
              {categories.map((c) => {
                const s = catTints(c.code, dark);
                const active = category === c.code;
                return (
                  <button
                    key={c.code}
                    type="button"
                    onClick={() => selectCat(c.code)}
                    title={`${c.code} / ${c.label_en} — ${c.definition}`}
                    className={clsx(
                      "w-full text-left px-3 py-2 flex items-center gap-2 text-xs transition-colors",
                      active ? clsx(ui.activeText, s.active, "ring-1") : clsx(s.chip, ui.hover)
                    )}
                  >
                    <span className="flex-1 min-w-0">
                      <span className="font-semibold">{c.code}</span>
                      <span className="block truncate opacity-80 text-[11px] leading-tight">{c.label_fr}</span>
                    </span>
                    <span className="opacity-60 tabular-nums">{c.count.toLocaleString()}</span>
                    <ChevronRight size={13} className={clsx("shrink-0", active ? "opacity-80" : "opacity-30")} />
                  </button>
                );
              })}
            </div>

            {/* ── Level 2: brands of the chosen category ─────────────────── */}
            <div className="flex-1 min-w-0 flex flex-col p-2.5 gap-2">
              {/* Search */}
              <div className="relative">
                <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  autoFocus
                  value={rawQ}
                  onChange={(e) => setRawQ(e.target.value)}
                  placeholder={category ? `Search ${category}…` : "Search all brands…"}
                  className={clsx("w-full pl-8 pr-8 py-1.5 rounded-lg border text-sm focus:outline-none focus:ring-1", ui.search)}
                />
                {isFetching && <Loader2 size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 animate-spin" />}
              </div>

              {activeDef && <p className="text-[11px] text-slate-500 leading-snug">{activeDef}</p>}

              {/* Header row + pagination */}
              <div className="flex items-center justify-between text-[11px] text-slate-400">
                <span>{total.toLocaleString()} {category ? `in ${category}` : "brands"}{q ? ` matching “${q}”` : ""}</span>
                <span className="flex items-center gap-1.5">
                  <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
                    className={clsx("p-0.5 rounded disabled:opacity-30", ui.pageHover)}><ChevronLeft size={14} /></button>
                  <span className="tabular-nums">{page}/{totalPages}</span>
                  <button type="button" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}
                    className={clsx("p-0.5 rounded disabled:opacity-30", ui.pageHover)}><ChevronRight size={14} /></button>
                </span>
              </div>

              {/* Brand list */}
              <ul className={clsx("flex-1 divide-y overflow-y-auto rounded-lg border", ui.divide, ui.listBorder)}>
                {brands.map((b) => {
                  const isSel = selectedId === b.id;
                  return (
                    <li key={b.id}>
                      <button
                        type="button"
                        onClick={() => choose(b)}
                        className={clsx(
                          "w-full text-left px-3 py-2 flex items-center gap-2 transition-colors",
                          isSel ? ui.rowSel : ui.rowHover
                        )}
                      >
                        <CatBadge code={b.primary_category} />
                        <span className={clsx("flex-1 min-w-0 truncate text-sm", ui.rowText)}>{b.name}</span>
                        {b.is_medicine && (
                          <span title="Registered medicine (SAM)" className="shrink-0"><Pill size={13} className="text-sky-300" /></span>
                        )}
                        {b.has_data ? (
                          <span title="Has linked data — live KPIs" className="shrink-0"><CircleDot size={13} className="text-emerald-400" /></span>
                        ) : (
                          <span title="No linked data yet" className="shrink-0"><CircleDashed size={13} className="text-slate-600" /></span>
                        )}
                        {isSel && <Check size={14} className="shrink-0 text-emerald-300" />}
                      </button>
                    </li>
                  );
                })}
                {brands.length === 0 && !isFetching && (
                  <li className="px-3 py-8 text-center text-sm text-slate-500">No brands match.</li>
                )}
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
