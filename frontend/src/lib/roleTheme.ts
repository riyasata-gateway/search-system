import {
  ShieldPlus, Megaphone, Briefcase, ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import type { Role } from "../hooks/useAuth";

/**
 * Per-role identity + accent system.
 *
 * The app ships one dark "command center" shell (see index.css). Rather than
 * fork pages per role, each role gets its own *identity* (product name, icon,
 * tagline) and a single accent colour that is injected as CSS variables on the
 * app shell (`--role-accent`, `--role-accent-rgb`). Those variables drive the
 * sidebar logo, active-nav indicator, focus glow and the workspace ambience, so
 * the whole product re-skins itself the moment the role changes — no per-page
 * edits required.
 *
 * Palette (product-owner sign-off 2026-06-07):
 *   pharmacist     → emerald  (clinical / patient-safety)
 *   marketing      → amber    (energetic / campaigns)
 *   brand_manager  → violet   (premium / strategic)
 *   admin          → brand-blue (neutral platform control)
 */
export interface RoleTheme {
  /** Solid accent hex — active nav, logo glow, key affordances. */
  accent: string;
  /** "r, g, b" triplet so we can build rgba() glows at any alpha. */
  accentRgb: string;
  /** Two-stop gradient for the sidebar logo mark + banner wash. */
  gradient: [string, string];
  /** Product name shown in the sidebar (replaces the generic "TDAH"). */
  product: string;
  /** One-line descriptor under the product name. */
  subtitle: string;
  /** Persona-facing tagline for the landing banner. */
  tagline: string;
  /** Lucide icon for the logo mark + banner. */
  Icon: LucideIcon;
}

export const ROLE_THEME: Record<Role, RoleTheme> = {
  pharmacist: {
    accent: "#22c55e",
    accentRgb: "34, 197, 94",
    gradient: ["#10b981", "#22c55e"],
    product: "Pharmacovigilance Console",
    subtitle: "Patient Safety & Dispensing Intelligence",
    tagline: "Monitor safety signals, shortages and demand across your pharmacy.",
    Icon: ShieldPlus,
  },
  marketing: {
    accent: "#f59e0b",
    accentRgb: "245, 158, 11",
    gradient: ["#f59e0b", "#fb923c"],
    product: "Campaign Intelligence",
    subtitle: "Reach, Resonance & Sentiment",
    tagline: "Track buzz, message resonance and audience sentiment for your brands.",
    Icon: Megaphone,
  },
  brand_manager: {
    accent: "#a486ff",
    accentRgb: "164, 134, 255",
    gradient: ["#885dfa", "#a486ff"],
    product: "Brand Command Center",
    subtitle: "Potential, Market & Risk Strategy",
    tagline: "Steer brand potential, launch readiness and competitive risk.",
    Icon: Briefcase,
  },
  admin: {
    accent: "#5b86ff",
    accentRgb: "91, 134, 255",
    gradient: ["#3f6dff", "#885dfa"],
    product: "Control Tower",
    subtitle: "Platform Administration",
    tagline: "Oversee every role, brand and signal across the platform.",
    Icon: ShieldCheck,
  },
};

export function themeFor(role?: Role | string | null): RoleTheme {
  return ROLE_THEME[(role as Role) ?? "admin"] ?? ROLE_THEME.admin;
}

/** CSS custom properties to spread onto the app shell for a given role. */
export function roleCssVars(role?: Role | string | null): React.CSSProperties {
  const t = themeFor(role);
  return {
    ["--role-accent" as any]: t.accent,
    ["--role-accent-rgb" as any]: t.accentRgb,
    ["--role-grad-from" as any]: t.gradient[0],
    ["--role-grad-to" as any]: t.gradient[1],
  };
}