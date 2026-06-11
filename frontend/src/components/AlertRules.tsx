import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { SlidersHorizontal, Plus, Trash2, Play, Power } from "lucide-react";
import { useSelectedBrand } from "../lib/selectedBrand";

/** B7 — user-defined saved alert rules (e.g. "BPI < 40 → notify"). In-app only;
 *  Slack/Teams/email delivery is B8 (deferred). */

type Rule = {
  id: number; name: string; metric: string; operator: string; threshold: number;
  brand_id: number | null; severity: string; active: boolean;
  last_triggered_at: string | null;
};

const METRICS: { v: string; label: string }[] = [
  { v: "bpi", label: "Brand Potential Index" },
  { v: "launch_readiness", label: "Launch readiness" },
  { v: "momentum", label: "Demand momentum" },
  { v: "sentiment", label: "Sentiment (% positive)" },
  { v: "complaint_rate", label: "Complaint rate (% negative)" },
  { v: "brand_trust", label: "Brand trust" },
  { v: "review_volume", label: "Review volume" },
];
const OPS: { v: string; label: string }[] = [
  { v: "lt", label: "<" }, { v: "lte", label: "≤" }, { v: "gt", label: ">" }, { v: "gte", label: "≥" },
];
const SEVERITIES = ["low", "medium", "high", "critical"];
const metricLabel = (v: string) => METRICS.find((m) => m.v === v)?.label ?? v;
const opLabel = (v: string) => OPS.find((o) => o.v === v)?.label ?? v;

export default function AlertRules() {
  const qc = useQueryClient();
  const [selectedBrand] = useSelectedBrand();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: "", metric: "bpi", operator: "lt", threshold: 40,
    severity: "medium", scope: "all" as "all" | "brand",
  });

  const { data: rules } = useQuery<Rule[]>({
    queryKey: ["alert-rules"],
    queryFn: () => apiClient.get("/alerts/rules").then((r) => r.data),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["alert-rules"] });
    qc.invalidateQueries({ queryKey: ["alerts"] });
  };

  const create = useMutation({
    mutationFn: () => apiClient.post("/alerts/rules", {
      name: form.name.trim() || `${metricLabel(form.metric)} ${opLabel(form.operator)} ${form.threshold}`,
      metric: form.metric, operator: form.operator, threshold: Number(form.threshold),
      severity: form.severity,
      brand_id: form.scope === "brand" && selectedBrand ? selectedBrand.id : null,
    }),
    onSuccess: () => { invalidate(); setOpen(false); setForm((f) => ({ ...f, name: "" })); },
  });
  const toggle = useMutation({
    mutationFn: (r: Rule) => apiClient.put(`/alerts/rules/${r.id}`, { ...r, active: !r.active }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: number) => apiClient.delete(`/alerts/rules/${id}`),
    onSuccess: invalidate,
  });
  const evaluate = useMutation({
    mutationFn: () => apiClient.post("/alerts/rules/evaluate").then((r) => r.data),
    onSuccess: invalidate,
  });

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
          <SlidersHorizontal size={15} className="text-indigo-500" /> Alert rules
          <span className="text-xs font-normal text-gray-400">notify me when a KPI crosses a threshold</span>
        </h2>
        <div className="flex items-center gap-2">
          <button onClick={() => evaluate.mutate()} disabled={evaluate.isPending}
            className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">
            <Play size={13} /> {evaluate.isPending ? "Checking…" : "Check now"}
          </button>
          <button onClick={() => setOpen((v) => !v)}
            className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700">
            <Plus size={13} /> New rule
          </button>
        </div>
      </div>

      {evaluate.data && (
        <p className="text-xs text-gray-500 mt-2">
          Checked your rules — {evaluate.data.new_alerts} new alert{evaluate.data.new_alerts === 1 ? "" : "s"} raised.
        </p>
      )}

      {open && (
        <div className="mt-3 rounded-lg border border-gray-200 bg-gray-50 p-3 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 items-end">
          <label className="col-span-2 text-xs text-gray-500">Name
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="optional" className="mt-1 w-full rounded border border-gray-200 px-2 py-1.5 text-sm" />
          </label>
          <label className="text-xs text-gray-500">Metric
            <select value={form.metric} onChange={(e) => setForm({ ...form, metric: e.target.value })}
              className="mt-1 w-full rounded border border-gray-200 px-2 py-1.5 text-sm">
              {METRICS.map((m) => <option key={m.v} value={m.v}>{m.label}</option>)}
            </select>
          </label>
          <label className="text-xs text-gray-500">Condition
            <select value={form.operator} onChange={(e) => setForm({ ...form, operator: e.target.value })}
              className="mt-1 w-full rounded border border-gray-200 px-2 py-1.5 text-sm">
              {OPS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
            </select>
          </label>
          <label className="text-xs text-gray-500">Threshold
            <input type="number" value={form.threshold}
              onChange={(e) => setForm({ ...form, threshold: Number(e.target.value) })}
              className="mt-1 w-full rounded border border-gray-200 px-2 py-1.5 text-sm" />
          </label>
          <label className="text-xs text-gray-500">Severity
            <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}
              className="mt-1 w-full rounded border border-gray-200 px-2 py-1.5 text-sm capitalize">
              {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="text-xs text-gray-500">Scope
            <select value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value as "all" | "brand" })}
              className="mt-1 w-full rounded border border-gray-200 px-2 py-1.5 text-sm">
              <option value="all">All my brands</option>
              <option value="brand" disabled={!selectedBrand}>
                {selectedBrand ? selectedBrand.name : "Pick a brand first"}
              </option>
            </select>
          </label>
          <button onClick={() => create.mutate()} disabled={create.isPending}
            className="col-span-2 sm:col-span-1 inline-flex items-center justify-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700">
            {create.isPending ? "Saving…" : "Save rule"}
          </button>
        </div>
      )}

      <div className="mt-3 space-y-1.5">
        {(rules ?? []).length === 0 && (
          <p className="text-xs text-gray-400 py-2">No rules yet — create one to get notified when a KPI crosses your threshold.</p>
        )}
        {(rules ?? []).map((r) => (
          <div key={r.id} className={`flex items-center gap-3 rounded-lg border px-3 py-2 ${r.active ? "border-gray-200 bg-white" : "border-gray-100 bg-gray-50 opacity-60"}`}>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 truncate">{r.name}</p>
              <p className="text-xs text-gray-500">
                {metricLabel(r.metric)} {opLabel(r.operator)} {r.threshold}
                {" · "}{r.brand_id ? "this brand" : "all my brands"}
                {" · "}<span className="capitalize">{r.severity}</span>
                {r.last_triggered_at && <span className="text-amber-600"> · last fired {new Date(r.last_triggered_at).toLocaleDateString("en-GB")}</span>}
              </p>
            </div>
            <button onClick={() => toggle.mutate(r)} title={r.active ? "Disable" : "Enable"}
              className={`shrink-0 p-1.5 rounded-lg border ${r.active ? "text-emerald-600 border-emerald-200" : "text-gray-400 border-gray-200"} hover:bg-gray-50`}>
              <Power size={14} />
            </button>
            <button onClick={() => remove.mutate(r.id)} title="Delete"
              className="shrink-0 p-1.5 rounded-lg border border-gray-200 text-gray-400 hover:text-red-500 hover:bg-gray-50">
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
