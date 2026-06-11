import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { Shield } from "lucide-react";

const STATUS_OPTIONS = ["reviewed", "escalated", "dismissed", "reported"];

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  reviewed: "bg-blue-100 text-blue-800",
  escalated: "bg-red-100 text-red-800",
  dismissed: "bg-gray-100 text-gray-500",
  reported: "bg-purple-100 text-purple-800",
};

export default function AdverseEventReview() {
  const queryClient = useQueryClient();
  const [filterStatus, setFilterStatus] = useState("pending");
  const [refInputs, setRefInputs] = useState<Record<number, string>>({});

  const { data: candidates, isLoading } = useQuery({
    queryKey: ["adverse-events", filterStatus],
    queryFn: () =>
      apiClient
        .get("/adverse-events/", { params: { review_status: filterStatus } })
        .then((r) => r.data),
  });

  const review = useMutation({
    mutationFn: ({ id, review_status, pharmacovigilance_ref }: any) =>
      apiClient.put(`/adverse-events/${id}/review`, { review_status, pharmacovigilance_ref }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["adverse-events"] }),
  });

  if (isLoading) return <div className="text-sm text-gray-500">Loading adverse event queue…</div>;

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-3 mb-1">
          <Shield size={22} className="text-red-500" />
          <h1 className="text-2xl font-bold text-gray-900">Adverse Event Review Queue</h1>
        </div>
        <p className="text-sm text-gray-500">
          Human review is mandatory for all adverse event candidates. The system does not make final decisions.
        </p>
      </div>

      <div className="flex gap-2">
        {["pending", "escalated", "reviewed", "reported", "dismissed"].map((s) => (
          <button
            key={s}
            onClick={() => setFilterStatus(s)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
              filterStatus === s
                ? "bg-blue-600 text-white border-blue-600"
                : "bg-white text-gray-600 border-gray-300 hover:border-blue-400"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {(candidates ?? []).length === 0 && (
        <div className="bg-white rounded-xl border border-gray-200 py-12 text-center">
          <Shield size={32} className="mx-auto text-gray-300 mb-2" />
          <p className="text-sm text-gray-400">No candidates with status: {filterStatus}</p>
        </div>
      )}

      <div className="space-y-4">
        {(candidates ?? []).map((c: any) => (
          <div key={c.id} className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  <span className="text-sm font-semibold text-gray-900">Candidate #{c.id}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLES[c.review_status]}`}>
                    {c.review_status}
                  </span>
                  {c.product_id && (
                    <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
                      Product ID: {c.product_id}
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-700 leading-relaxed">{c.description}</p>
                <div className="mt-2 flex gap-4 text-xs text-gray-400">
                  <span>Mention: {c.mention_id?.slice(0, 8)}…</span>
                  <span>Created: {new Date(c.created_at).toLocaleDateString("en-GB")}</span>
                  {c.notification_sent_at && (
                    <span className="text-blue-500">
                      Notified: {new Date(c.notification_sent_at).toLocaleDateString("en-GB")}
                    </span>
                  )}
                </div>
                {c.pharmacovigilance_ref && (
                  <p className="text-xs text-purple-700 mt-1 font-medium">
                    PV Ref: {c.pharmacovigilance_ref}
                  </p>
                )}
              </div>
            </div>

            {c.review_status === "pending" && (
              <div className="border-t border-gray-100 pt-4 space-y-3">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Pharmacovigilance reference (optional — assign before escalating)
                  </label>
                  <input
                    type="text"
                    value={refInputs[c.id] ?? ""}
                    onChange={(e) => setRefInputs((prev) => ({ ...prev, [c.id]: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g. PV-2024-001234"
                  />
                </div>
                <div className="flex gap-2 flex-wrap">
                  {STATUS_OPTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() =>
                        review.mutate({
                          id: c.id,
                          review_status: s,
                          pharmacovigilance_ref: refInputs[c.id] || undefined,
                        })
                      }
                      disabled={review.isPending}
                      className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors disabled:opacity-50 ${
                        s === "escalated"
                          ? "bg-red-600 text-white border-red-600 hover:bg-red-700"
                          : s === "reported"
                          ? "bg-purple-600 text-white border-purple-600 hover:bg-purple-700"
                          : s === "dismissed"
                          ? "border-gray-300 text-gray-600 hover:bg-gray-50"
                          : "bg-blue-600 text-white border-blue-600 hover:bg-blue-700"
                      }`}
                    >
                      Mark as {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
