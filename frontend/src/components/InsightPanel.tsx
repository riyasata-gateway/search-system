import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { Sparkles, Loader2, Send, Quote } from "lucide-react";

/** C-bucket — semantic insight over the ingested corpus (RAG). Lens selects the
 *  source set: consumer voice (reviews), patient talk (forums), evidence (PubMed).
 *  On-demand (LLM call only when the user asks) to control cost. */

type Source = { pmid?: string | null; journal?: string | null; source_type?: string | null; score: number };
type InsightResp = { brand: string; query: string; answer: string | null; sources: Source[]; note?: string };

const LENSES = [
  { v: "voice", label: "Consumer voice", hint: "what patients say in reviews" },
  { v: "patient", label: "Patient talk", hint: "forum & social discussion" },
  { v: "evidence", label: "Evidence", hint: "clinical literature (PubMed)" },
] as const;

export default function InsightPanel({ brandId }: { brandId: number | null }) {
  const [lens, setLens] = useState<string>("voice");
  const [q, setQ] = useState("");

  const ask = useMutation<InsightResp, unknown, void>({
    mutationFn: () =>
      apiClient.get(`/intelligence/insight/${brandId}`, {
        params: { lens, q: q.trim() || undefined }, timeout: 60_000,
      }).then((r) => r.data),
  });

  if (brandId == null) return null;
  const data = ask.data;

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className="flex items-center justify-between gap-2 flex-wrap mb-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
          <Sparkles size={14} className="text-indigo-500" /> Ask the corpus
          <span className="font-normal normal-case text-slate-400">grounded, cited insight from our ingested data</span>
        </h3>
        <div className="flex rounded-lg border border-slate-200 overflow-hidden text-xs">
          {LENSES.map((l) => (
            <button key={l.v} onClick={() => setLens(l.v)} title={l.hint}
              className={`px-2.5 py-1.5 ${lens === l.v ? "bg-indigo-600 text-white" : "bg-white text-slate-600 hover:bg-slate-50"}`}>
              {l.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <input
          value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !ask.isPending) ask.mutate(); }}
          placeholder={`Ask about this brand — e.g. "main complaints", "tolerability"… (blank = summary)`}
          className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm"
        />
        <button onClick={() => ask.mutate()} disabled={ask.isPending}
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm font-semibold hover:bg-indigo-700 disabled:opacity-60">
          {ask.isPending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          {ask.isPending ? "Thinking…" : "Ask"}
        </button>
      </div>

      {ask.isError && <p className="text-xs text-rose-500 mt-2">Couldn't generate an insight — try again.</p>}

      {data && (
        <div className="mt-3">
          {data.answer ? (
            <>
              <p className="text-[13px] text-slate-700 leading-relaxed whitespace-pre-wrap">{data.answer}</p>
              {data.sources.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <Quote size={12} className="text-slate-400" />
                  {data.sources.map((s, i) => (
                    <span key={i} className="text-[10px] text-slate-500 bg-slate-50 border border-slate-200 rounded-full px-2 py-0.5">
                      {s.pmid ? `PMID ${s.pmid}` : (s.source_type ?? "source")}{s.journal ? ` · ${s.journal}` : ""}
                    </span>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p className="text-xs text-slate-400">{data.note ?? "No indexed text for this brand/lens yet."}</p>
          )}
        </div>
      )}
    </div>
  );
}
