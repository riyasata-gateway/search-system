import { useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";

export type Role = "pharmacist" | "marketing" | "brand_manager" | "admin";

export interface AuthUser {
  role: Role;
}

export function useAuth() {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<AuthUser | null>(() => {
    const role = localStorage.getItem("user_role");
    return role ? { role: role as AuthUser["role"] } : null;
  });

  const login = useCallback(async (email: string, password: string) => {
    const params = new URLSearchParams();
    params.append("username", email);
    params.append("password", password);
    const res = await apiClient.post("/auth/login", params, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    localStorage.setItem("access_token", res.data.access_token);
    localStorage.setItem("refresh_token", res.data.refresh_token);
    localStorage.setItem("user_role", res.data.role);
    // Drop any cached data from a previous session so one role never sees
    // another role's cached responses (role-scoped data must not leak/persist).
    queryClient.clear();
    setUser({ role: res.data.role });
    return res.data.role;
  }, [queryClient]);

  const logout = useCallback(() => {
    localStorage.clear();
    queryClient.clear();
    setUser(null);
  }, [queryClient]);

  return { user, login, logout };
}
