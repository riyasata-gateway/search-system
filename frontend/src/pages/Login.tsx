import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { Sparkles } from "lucide-react";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const role = await login(email, password);
      if (role === "pharmacist") navigate("/pharmacist");
      else if (role === "marketing" || role === "brand_manager") navigate("/lab");
      else navigate("/admin");
    } catch {
      setError("Invalid email or password.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-ink-950 via-ink-900 to-ink-950 flex items-center justify-center p-4 relative overflow-hidden">
      {/* Soft TDAH grid backdrop */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(63,109,255,0.22),transparent_55%),radial-gradient(ellipse_at_bottom_left,rgba(136,93,250,0.16),transparent_55%)] pointer-events-none" />
      <div className="absolute inset-0 bg-grid-soft bg-grid-soft opacity-[0.05] pointer-events-none [mask-image:radial-gradient(ellipse_at_center,black_10%,transparent_70%)]" />

      <div className="relative w-full max-w-md p-8 rounded-2xl border border-white/10
                      bg-white/[0.045] backdrop-blur-xl ring-1 ring-white/5
                      shadow-[0_0_0_1px_rgba(91,134,255,0.15),0_30px_80px_-30px_rgba(91,134,255,0.45)]">
        <div className="flex items-center gap-3 mb-1">
          <div className="relative bg-gradient-to-br from-brand-500 via-accent-500 to-accent-600 text-white p-2.5 rounded-xl shadow-lg shadow-accent-500/40">
            <Sparkles size={22} strokeWidth={2.4} />
            <span className="absolute -right-1 -top-1 w-2.5 h-2.5 rounded-full bg-emerald-400 ring-2 ring-[#0b0f1a] animate-pulse" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-gradient">TDAH</h1>
            <p className="text-[11px] uppercase tracking-wider text-slate-500">Trend Data Aggregator Hyperintelligent</p>
          </div>
        </div>
        <p className="text-xs text-slate-400 leading-relaxed mb-7 mt-3">
          Hyperintelligent pharma trend, sentiment, and brand-potential engine for the EU market.
        </p>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg px-3 py-2.5 text-sm text-white bg-slate-950/50 border border-white/10 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-brand-400 transition"
              placeholder="you@pharmacy.eu"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg px-3 py-2.5 text-sm text-white bg-slate-950/50 border border-white/10 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-brand-400 transition"
              placeholder="••••••••"
              required
            />
          </div>
          {error && <p className="text-sm text-red-300 bg-red-500/10 border border-red-400/20 rounded-lg px-3 py-2">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-gradient-to-br from-brand-600 via-accent-600 to-accent-700 hover:from-brand-700 hover:via-accent-700 hover:to-accent-800 text-white font-semibold py-2.5 rounded-lg transition-all shadow-lg shadow-accent-600/30 disabled:opacity-50"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-center text-[10px] uppercase tracking-[0.16em] text-slate-500">
          DIA · Data → Intelligence → Action
        </p>
      </div>
    </div>
  );
}
