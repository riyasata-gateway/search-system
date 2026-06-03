import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Brand — refined indigo with a hint of teal.
        // Reads as "clinical / trustworthy / data-forward" without feeling cold.
        brand: {
          50:  "#eef4ff",
          100: "#dee9ff",
          200: "#c2d6ff",
          300: "#97b8ff",
          400: "#6592ff",
          500: "#3f6dff",
          600: "#2a4ff5",
          700: "#213fdf",
          800: "#1f36b3",
          900: "#1f338c",
          950: "#171f50",
        },
        // AI accent — a slightly cooler violet that sits beside brand without clashing.
        accent: {
          50:  "#f6f4ff",
          100: "#ede9ff",
          200: "#dcd4ff",
          300: "#c2b1ff",
          400: "#a486ff",
          500: "#885dfa",
          600: "#7842ee",
          700: "#6932d2",
          800: "#552aaa",
          900: "#46258a",
          950: "#2a1660",
        },
        // Enterprise navy — the dark left rail. A deep, slightly blue-cool slate
        // that reads as "authoritative / corporate" against the bright workspace.
        ink: {
          50:  "#f3f5f9",
          100: "#e5e9f1",
          200: "#c8d1e1",
          300: "#9caacb",
          400: "#6c7da3",
          500: "#4a5a80",
          600: "#374466",
          700: "#28324d",   // hover surface on the rail
          800: "#1a2236",   // rail mid
          900: "#111726",   // rail base
          950: "#0b0f1a",   // rail deep / gradient foot
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      boxShadow: {
        // Soft elevation — preferred over flat borders for a premium feel.
        soft:         "0 1px 2px rgba(15, 23, 42, 0.04), 0 1px 3px rgba(15, 23, 42, 0.04)",
        elevated:     "0 4px 16px -4px rgba(15, 23, 42, 0.08), 0 2px 6px -1px rgba(15, 23, 42, 0.04)",
        floating:     "0 12px 32px -12px rgba(15, 23, 42, 0.12), 0 4px 12px -4px rgba(15, 23, 42, 0.08)",
        "ring-brand":  "0 0 0 4px rgba(63, 109, 255, 0.12)",
        "ring-accent": "0 0 0 4px rgba(136, 93, 250, 0.14)",
        // Crisp depth for the dark rail so it lifts off the bright workspace.
        rail:          "1px 0 0 0 rgba(15,23,42,0.06), 4px 0 24px -8px rgba(11,15,26,0.45)",
        // ── Dark "command center" glow shadows ──────────────────────────────
        "glow-brand":  "0 0 0 1px rgba(63,109,255,0.25), 0 8px 30px -8px rgba(63,109,255,0.35)",
        "glow-accent": "0 0 0 1px rgba(136,93,250,0.25), 0 8px 30px -8px rgba(136,93,250,0.40)",
        "glow-cyan":   "0 0 0 1px rgba(34,211,238,0.22), 0 8px 30px -8px rgba(34,211,238,0.30)",
        "card-dark":   "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 20px 40px -24px rgba(0,0,0,0.7)",
      },
      dropShadow: {
        glow: "0 0 10px rgba(136,93,250,0.45)",
      },
      keyframes: {
        shimmer: {
          "0%":   { backgroundPosition: "-468px 0" },
          "100%": { backgroundPosition: "468px 0" },
        },
        "pulse-ring": {
          "0%":   { transform: "scale(0.8)", opacity: "0.7" },
          "80%":  { transform: "scale(1.6)", opacity: "0" },
          "100%": { transform: "scale(1.6)", opacity: "0" },
        },
        "fade-up": {
          "0%":   { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        shimmer:      "shimmer 1.4s ease-in-out infinite linear",
        "pulse-ring": "pulse-ring 1.6s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-up":    "fade-up 240ms ease-out",
      },
      backgroundImage: {
        "grid-soft":
          "linear-gradient(rgba(15,23,42,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(15,23,42,0.035) 1px, transparent 1px)",
      },
      backgroundSize: {
        "grid-soft": "32px 32px",
      },
    },
  },
  plugins: [],
} satisfies Config;
