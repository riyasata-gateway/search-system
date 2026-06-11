import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { Users, FileText, UserPlus, UserX } from "lucide-react";

const ROLE_STYLES: Record<string, string> = {
  admin: "bg-red-100 text-red-700",
  pharmacist: "bg-blue-100 text-blue-700",
  marketing: "bg-amber-100 text-amber-700",
  brand_manager: "bg-purple-100 text-purple-700",
};

export default function Admin() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"users" | "audit">("users");
  const [newUser, setNewUser] = useState({ email: "", password: "", role: "pharmacist", pharmacy_id: "", brand_group_id: "" });

  const { data: users } = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => apiClient.get("/admin/users").then((r) => r.data),
  });

  const { data: pharmacies } = useQuery({
    queryKey: ["admin-pharmacies"],
    queryFn: () => apiClient.get("/admin/pharmacies").then((r) => r.data),
  });

  const { data: brandGroups } = useQuery({
    queryKey: ["admin-brand-groups"],
    queryFn: () => apiClient.get("/admin/brand-groups").then((r) => r.data),
  });

  const { data: auditLogs } = useQuery({
    queryKey: ["audit-logs"],
    queryFn: () => apiClient.get("/admin/audit-logs", { params: { limit: 100 } }).then((r) => r.data),
    enabled: tab === "audit",
  });

  const isPharmacist = newUser.role === "pharmacist";
  const isLab = newUser.role === "marketing" || newUser.role === "brand_manager";

  const createUser = useMutation({
    mutationFn: (data: typeof newUser) =>
      apiClient.post("/admin/users", {
        email: data.email,
        password: data.password,
        role: data.role,
        pharmacy_id: data.role === "pharmacist" && data.pharmacy_id ? Number(data.pharmacy_id) : null,
        brand_group_id:
          (data.role === "marketing" || data.role === "brand_manager") && data.brand_group_id
            ? Number(data.brand_group_id)
            : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      setNewUser({ email: "", password: "", role: "pharmacist", pharmacy_id: "", brand_group_id: "" });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) => apiClient.put(`/admin/users/${id}/deactivate`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Admin</h1>

      <div className="flex gap-2">
        {(["users", "audit"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
              tab === t
                ? "bg-blue-600 text-white border-blue-600"
                : "bg-white text-gray-600 border-gray-300 hover:border-blue-400"
            }`}
          >
            {t === "users" ? <><Users size={14} className="inline mr-1.5" />Users</> : <><FileText size={14} className="inline mr-1.5" />Audit Logs</>}
          </button>
        ))}
      </div>

      {tab === "users" && (
        <div className="space-y-6">
          <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
            <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2">
              <UserPlus size={16} /> Create User
            </h2>
            <div className="grid grid-cols-3 gap-3">
              <input
                type="email"
                placeholder="Email"
                value={newUser.email}
                onChange={(e) => setNewUser((u) => ({ ...u, email: e.target.value }))}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <input
                type="password"
                placeholder="Password"
                value={newUser.password}
                onChange={(e) => setNewUser((u) => ({ ...u, password: e.target.value }))}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <select
                value={newUser.role}
                onChange={(e) => setNewUser((u) => ({ ...u, role: e.target.value }))}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="pharmacist">Pharmacist</option>
                <option value="marketing">Marketing</option>
                <option value="brand_manager">Brand Manager</option>
                <option value="admin">Admin</option>
              </select>
              {isPharmacist && (
                <select
                  value={newUser.pharmacy_id}
                  onChange={(e) => setNewUser((u) => ({ ...u, pharmacy_id: e.target.value }))}
                  className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">— assign pharmacy (optional) —</option>
                  {(pharmacies ?? []).map((p: any) => (
                    <option key={p.id} value={p.id}>
                      {p.name}{p.city ? ` · ${p.city}` : ""}
                    </option>
                  ))}
                </select>
              )}
              {isLab && (
                <select
                  value={newUser.brand_group_id}
                  onChange={(e) => setNewUser((u) => ({ ...u, brand_group_id: e.target.value }))}
                  className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">— assign brand group (optional) —</option>
                  {(brandGroups ?? []).map((g: any) => (
                    <option key={g.id} value={g.id}>
                      {g.name?.replace(/_/g, " ")}
                    </option>
                  ))}
                </select>
              )}
            </div>
            <button
              onClick={() => createUser.mutate(newUser)}
              disabled={!newUser.email || !newUser.password || createUser.isPending}
              className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
            >
              {createUser.isPending ? "Creating…" : "Create User"}
            </button>
            {createUser.isError && (
              <p className="text-sm text-red-600">Failed to create user. Email may already exist.</p>
            )}
          </div>

          <div className="bg-white rounded-xl border border-gray-200">
            <div className="px-5 py-4 border-b border-gray-100">
              <h2 className="text-base font-semibold text-gray-900">Users ({users?.length ?? 0})</h2>
            </div>
            <div className="divide-y divide-gray-50">
              {(users ?? []).map((u: any) => (
                <div key={u.id} className="px-5 py-3.5 flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-900">{u.email}</span>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ROLE_STYLES[u.role]}`}>
                        {u.role?.replace("_", " ")}
                      </span>
                      {!u.is_active && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-400">inactive</span>
                      )}
                    </div>
                    <p className="text-xs text-gray-400 mt-0.5">
                      Created: {new Date(u.created_at).toLocaleDateString("en-GB")}
                      {u.last_login && ` · Last login: ${new Date(u.last_login).toLocaleDateString("en-GB")}`}
                    </p>
                  </div>
                  {u.is_active && (
                    <button
                      onClick={() => deactivate.mutate(u.id)}
                      className="text-gray-400 hover:text-red-500 p-1.5 rounded"
                      title="Deactivate"
                    >
                      <UserX size={15} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {tab === "audit" && (
        <div className="bg-white rounded-xl border border-gray-200">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-base font-semibold text-gray-900">Audit Logs (last 100)</h2>
          </div>
          <div className="divide-y divide-gray-50 max-h-[600px] overflow-auto">
            {(auditLogs ?? []).map((log: any) => (
              <div key={log.id} className="px-5 py-3 flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-semibold text-gray-700">{log.action}</span>
                    <span className="text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">{log.resource_type}</span>
                    {log.resource_id && (
                      <span className="text-xs text-gray-400">#{log.resource_id}</span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5">
                    User #{log.user_id ?? "system"} · {log.ip_address} · {new Date(log.timestamp).toLocaleString("en-GB")}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
