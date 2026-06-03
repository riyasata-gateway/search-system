import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { Bell, CheckCircle, AlertTriangle, Shield, TrendingUp, Info } from "lucide-react";

// Dark-theme-native severity styles. We use translucent colour washes + light
// text (arbitrary /opacity utilities) rather than Tailwind's light *-50/*-800
// pairs, which the global dark reskin only partially remaps and which left text
// unreadable on dark cards.
const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-500/10 border-red-500/30 text-red-200",
  high: "bg-orange-500/10 border-orange-500/30 text-orange-200",
  medium: "bg-amber-500/10 border-amber-500/30 text-amber-100",
  low: "bg-blue-500/10 border-blue-500/30 text-blue-200",
};

const TYPE_ICONS: Record<string, React.ReactNode> = {
  adverse_event: <Shield size={16} className="text-red-500" />,
  shortage: <AlertTriangle size={16} className="text-orange-500" />,
  misinformation: <Info size={16} className="text-yellow-500" />,
  competitor_spike: <TrendingUp size={16} className="text-blue-500" />,
  brand_spike: <TrendingUp size={16} className="text-green-500" />,
  prescription_promotion: <Shield size={16} className="text-purple-500" />,
};

export default function Alerts() {
  const queryClient = useQueryClient();

  const { data: alerts, isLoading } = useQuery({
    queryKey: ["alerts"],
    queryFn: () => apiClient.get("/alerts/").then((r) => r.data),
    refetchInterval: 30_000,
  });

  const acknowledge = useMutation({
    mutationFn: (id: number) => apiClient.put(`/alerts/${id}/acknowledge`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const unacknowledged = (alerts ?? []).filter((a: any) => !a.acknowledged_at);
  const acknowledged = (alerts ?? []).filter((a: any) => a.acknowledged_at);

  if (isLoading) return <div className="text-sm text-gray-500">Loading alerts…</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold text-gray-900">Alerts</h1>
        {unacknowledged.length > 0 && (
          <span className="bg-red-500 text-white text-xs font-bold px-2 py-0.5 rounded-full">
            {unacknowledged.length}
          </span>
        )}
      </div>

      {unacknowledged.length === 0 && acknowledged.length === 0 && (
        <div className="bg-white rounded-xl border border-gray-200 py-12 text-center">
          <Bell size={32} className="mx-auto text-gray-300 mb-2" />
          <p className="text-sm text-gray-400">No alerts yet.</p>
        </div>
      )}

      {unacknowledged.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Active</h2>
          {unacknowledged.map((alert: any) => (
            <div
              key={alert.id}
              className={`rounded-xl border p-4 ${SEVERITY_STYLES[alert.severity] ?? "bg-gray-50 border-gray-200"}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3 flex-1">
                  <div className="mt-0.5">{TYPE_ICONS[alert.alert_type] ?? <Bell size={16} />}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="text-xs font-semibold uppercase tracking-wide">
                        {alert.alert_type?.replace(/_/g, " ")}
                      </span>
                      <span className="text-xs opacity-70 capitalize">{alert.severity}</span>
                      {alert.count > 1 && (
                        <span className="text-xs font-semibold px-1.5 py-0.5 rounded-full bg-white/10 border border-current">
                          ×{alert.count} mentions
                        </span>
                      )}
                    </div>
                    <p className="text-sm leading-relaxed">{alert.description}</p>
                    <p className="text-xs opacity-60 mt-1">
                      {new Date(alert.created_at).toLocaleString("en-GB")}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => acknowledge.mutate(alert.id)}
                  disabled={acknowledge.isPending}
                  className="shrink-0 flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 bg-white/10 border border-current rounded-lg hover:bg-white/20 transition-colors"
                >
                  <CheckCircle size={13} />
                  Acknowledge
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {acknowledged.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Acknowledged</h2>
          {acknowledged.slice(0, 20).map((alert: any) => (
            <div key={alert.id} className="bg-white border border-gray-200 rounded-xl p-4 opacity-60">
              <div className="flex items-center gap-3">
                <div>{TYPE_ICONS[alert.alert_type] ?? <Bell size={16} />}</div>
                <div className="flex-1 min-w-0">
                  <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                    {alert.alert_type?.replace(/_/g, " ")}
                  </span>
                  <p className="text-sm text-gray-600 truncate">{alert.description}</p>
                </div>
                <span className="text-xs text-gray-400 shrink-0">
                  {new Date(alert.acknowledged_at).toLocaleDateString("en-GB")}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
