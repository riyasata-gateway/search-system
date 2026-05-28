import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { Plus, Trash2, Save } from "lucide-react";

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

  const [form, setForm] = useState({
    name: "",
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
      setForm({ ...form, name: "" });
    },
  });

  const deleteTopic = useMutation({
    mutationFn: (id: number) => apiClient.delete(`/search-topics/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["search-topics"] }),
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
          <label className="block text-sm font-medium text-gray-700 mb-1">Topic name</label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. Dafalgan BE/FR monitoring"
          />
        </div>

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
          disabled={!form.name || createTopic.isPending}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
        >
          <Plus size={16} />
          {createTopic.isPending ? "Saving…" : "Add topic"}
        </button>
      </div>

      {topics?.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-base font-semibold text-gray-900">Active topics</h2>
          </div>
          <div className="divide-y divide-gray-50">
            {topics.map((t: any) => (
              <div key={t.id} className="px-5 py-3.5 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-900">{t.name}</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {t.countries?.join(", ")} · {t.languages?.join(", ")} · {t.time_window}
                  </p>
                </div>
                <button
                  onClick={() => deleteTopic.mutate(t.id)}
                  className="text-gray-400 hover:text-red-500 p-1.5 rounded"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
