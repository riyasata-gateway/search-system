import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { Plus, Trash2, RefreshCw } from "lucide-react";

interface Brand { id: number; name: string; manufacturer: string | null; is_competitor: boolean; }

const COUNTRIES = ["BE", "FR", "NL", "DE"];
const LANGUAGES = ["fr", "nl", "en", "de"];
const TIME_WINDOWS = ["7d", "30d", "90d"];
const SOURCE_TYPES = ["google_trends", "reddit", "rss", "forum", "youtube", "licensed_api"];

export default function BrandSetup() {
  const queryClient = useQueryClient();
  const { data: topics } = useQuery({
    queryKey: ["search-topics"],
    queryFn: () => apiClient.get("/search-topics/").then((r) => r.data),
  });
  const { data: brands } = useQuery<Brand[]>({
    queryKey: ["brands"],
    queryFn: () => apiClient.get("/brands/").then((r) => r.data),
  });

  const [form, setForm] = useState({
    name: "",
    brand_id: null as number | null,
    countries: ["BE", "FR"],
    languages: ["fr", "nl", "en"],
    time_window: "30d",
    competitor_brand_ids: [] as number[],
    sources: SOURCE_TYPES.map((st) => ({ source_type: st, is_enabled: st !== "licensed_api" && st !== "youtube" })),
  });

  const createTopic = useMutation({
    mutationFn: (data: typeof form) => apiClient.post("/search-topics/", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["search-topics"] });
      setForm((f) => ({ ...f, name: "", brand_id: null, competitor_brand_ids: [] }));
    },
  });

  // Selecting a brand is what links the topic (step 3) back to the brand (step 1),
  // so ingestion collects for the user's preferred brand. Auto-fill the topic name.
  const selectBrand = (id: number) =>
    setForm((f) => {
      const b = brands?.find((x) => x.id === id);
      return {
        ...f,
        brand_id: id,
        name: f.name.trim() ? f.name : b ? `${b.name} monitoring` : f.name,
        competitor_brand_ids: f.competitor_brand_ids.filter((c) => c !== id),
      };
    });

  const toggleCompetitor = (id: number) =>
    setForm((f) => ({
      ...f,
      competitor_brand_ids: f.competitor_brand_ids.includes(id)
        ? f.competitor_brand_ids.filter((c) => c !== id)
        : [...f.competitor_brand_ids, id],
    }));

  const deleteTopic = useMutation({
    mutationFn: (id: number) => apiClient.delete(`/search-topics/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["search-topics"] }),
  });

  // "Collect now" — kick off ingestion for a topic's enabled sources.
  const [collectMsg, setCollectMsg] = useState<Record<number, { text: string; error?: boolean }>>({});
  const collectNow = useMutation({
    mutationFn: (id: number) => apiClient.post(`/ingestion/topics/${id}/collect`).then((r) => r.data),
    onSuccess: (data) => {
      const sources = Object.keys(data.dispatched);
      setCollectMsg((m) => ({
        ...m,
        [data.topic_id]: {
          text: sources.length
            ? `Queued ${sources.length} source${sources.length > 1 ? "s" : ""}: ${sources.join(", ")}`
            : "No enabled sources to collect.",
          error: sources.length === 0,
        },
      }));
    },
    onError: (err: any, id) => {
      setCollectMsg((m) => ({
        ...m,
        [id]: { text: err?.response?.data?.detail ?? "Failed to start collection.", error: true },
      }));
    },
  });

  const toggleCountry = (c: string) =>
    setForm((f) => ({
      ...f,
      countries: f.countries.includes(c) ? f.countries.filter((x) => x !== c) : [...f.countries, c],
    }));

  const toggleLanguage = (l: string) =>
    setForm((f) => ({
      ...f,
      languages: f.languages.includes(l) ? f.languages.filter((x) => x !== l) : [...f.languages, l],
    }));

  const toggleSource = (st: string) =>
    setForm((f) => ({
      ...f,
      sources: f.sources.map((s) => (s.source_type === st ? { ...s, is_enabled: !s.is_enabled } : s)),
    }));

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Brand / Topic Setup</h1>
        <p className="text-sm text-gray-500">Configure what to monitor — brand, competitors, markets, and sources.</p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-5">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Brand to monitor <span className="text-red-500">*</span>
          </label>
          <select
            value={form.brand_id ?? ""}
            onChange={(e) => e.target.value && selectBrand(Number(e.target.value))}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Select your brand…</option>
            {(brands ?? [])
              .filter((b) => !b.is_competitor)
              .map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}{b.manufacturer ? ` · ${b.manufacturer}` : ""}
                </option>
              ))}
          </select>
          <p className="text-xs text-gray-400 mt-1">
            Links this topic to a brand so ingestion collects for it and the dashboards scope to it.
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Topic name</label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. Dafalgan BE/FR monitoring"
          />
        </div>

        {form.brand_id != null && (brands ?? []).some((b) => b.id !== form.brand_id) && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Competitors to track</label>
            <div className="flex gap-2 flex-wrap">
              {(brands ?? [])
                .filter((b) => b.id !== form.brand_id)
                .map((b) => (
                  <button
                    key={b.id}
                    onClick={() => toggleCompetitor(b.id)}
                    className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                      form.competitor_brand_ids.includes(b.id)
                        ? "bg-purple-600 text-white border-purple-600"
                        : "bg-white text-gray-600 border-gray-300 hover:border-purple-400"
                    }`}
                  >
                    {b.name}
                  </button>
                ))}
            </div>
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Markets</label>
          <div className="flex gap-2 flex-wrap">
            {COUNTRIES.map((c) => (
              <button
                key={c}
                onClick={() => toggleCountry(c)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                  form.countries.includes(c)
                    ? "bg-blue-600 text-white border-blue-600"
                    : "bg-white text-gray-600 border-gray-300 hover:border-blue-400"
                }`}
              >
                {c}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Languages</label>
          <div className="flex gap-2 flex-wrap">
            {LANGUAGES.map((l) => (
              <button
                key={l}
                onClick={() => toggleLanguage(l)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                  form.languages.includes(l)
                    ? "bg-indigo-600 text-white border-indigo-600"
                    : "bg-white text-gray-600 border-gray-300 hover:border-indigo-400"
                }`}
              >
                {l}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Time window</label>
          <div className="flex gap-2">
            {TIME_WINDOWS.map((tw) => (
              <button
                key={tw}
                onClick={() => setForm((f) => ({ ...f, time_window: tw }))}
                className={`px-4 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                  form.time_window === tw
                    ? "bg-green-600 text-white border-green-600"
                    : "bg-white text-gray-600 border-gray-300 hover:border-green-400"
                }`}
              >
                {tw}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Data sources</label>
          <div className="grid grid-cols-2 gap-2">
            {form.sources.map((s) => (
              <label key={s.source_type} className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={s.is_enabled}
                  onChange={() => toggleSource(s.source_type)}
                  className="rounded"
                />
                <span className="text-sm text-gray-700 capitalize">{s.source_type.replace("_", " ")}</span>
              </label>
            ))}
          </div>
        </div>

        <button
          onClick={() => createTopic.mutate(form)}
          disabled={!form.name || form.brand_id == null || createTopic.isPending}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
        >
          <Plus size={16} />
          {createTopic.isPending ? "Saving…" : "Add topic"}
        </button>
        {form.brand_id == null && (
          <p className="text-xs text-amber-600">Select a brand to monitor before adding the topic.</p>
        )}
      </div>

      {topics?.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-base font-semibold text-gray-900">Active topics</h2>
          </div>
          <div className="divide-y divide-gray-50">
            {topics.map((t: any) => (
              <div key={t.id} className="px-5 py-3.5">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-gray-900">
                      {t.name}
                      {t.brand_id != null && (
                        <span className="ml-2 text-xs font-normal text-blue-600">
                          → {brands?.find((b) => b.id === t.brand_id)?.name ?? `brand #${t.brand_id}`}
                        </span>
                      )}
                    </p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {t.countries?.join(", ")} · {t.languages?.join(", ")} · {t.time_window}
                    </p>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => collectNow.mutate(t.id)}
                      disabled={collectNow.isPending && collectNow.variables === t.id}
                      className="flex items-center gap-1.5 text-xs font-medium text-blue-600 border border-blue-200 hover:bg-blue-50 px-2.5 py-1.5 rounded-lg disabled:opacity-50"
                    >
                      <RefreshCw size={13} className={collectNow.isPending && collectNow.variables === t.id ? "animate-spin" : ""} />
                      {collectNow.isPending && collectNow.variables === t.id ? "Starting…" : "Collect now"}
                    </button>
                    <button
                      onClick={() => deleteTopic.mutate(t.id)}
                      className="text-gray-400 hover:text-red-500 p-1.5 rounded"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>
                {collectMsg[t.id] && (
                  <p className={`text-xs mt-1.5 ${collectMsg[t.id].error ? "text-amber-600" : "text-green-600"}`}>
                    {collectMsg[t.id].text}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
