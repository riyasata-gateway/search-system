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
      else if (role === "lab_user") navigate("/lab");
      else navigate("/admin");
    } catch {
      setError("Invalid email or password.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-indigo-950 to-violet-950 flex items-center justify-center p-4 relative overflow-hidden">
      {/* Soft TDAH grid backdrop */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(99,102,241,0.25),transparent_55%),radial-gradient(ellipse_at_bottom_left,rgba(167,139,250,0.18),transparent_55%)] pointer-events-none" />

      <div className="relative bg-white/95 backdrop-blur rounded-2xl shadow-2xl w-full max-w-md p-8 ring-1 ring-white/10">
        <div className="flex items-center gap-3 mb-1">
          <div className="relative bg-gradient-to-br from-indigo-500 via-violet-500 to-fuchsia-500 text-white p-2.5 rounded-xl shadow-lg shadow-violet-500/30">
            <Sparkles size={22} strokeWidth={2.4} />
            <span className="absolute -right-1 -top-1 w-2.5 h-2.5 rounded-full bg-emerald-400 ring-2 ring-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">TDAH</h1>
            <p className="text-[11px] uppercase tracking-wider text-slate-400">Trend Data Aggregator Hyperintelligent</p>
          </div>
        </div>
        <p className="text-xs text-slate-500 leading-relaxed mb-7 mt-3">
          Hyperintelligent pharma trend, sentiment, and brand-potential engine for the EU market.
        </p>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-violet-400 transition"
              placeholder="you@pharmacy.eu"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-violet-400 transition"
              placeholder="••••••••"
              required
            />
          </div>
          {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-600 hover:from-indigo-700 hover:via-violet-700 hover:to-fuchsia-700 text-white font-semibold py-2.5 rounded-lg transition-all shadow-lg shadow-violet-600/20 disabled:opacity-50"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-center text-[10px] uppercase tracking-[0.16em] text-slate-400">
          DIA · Data → Intelligence → Action
        </p>
      </div>
    </div>
  );
}
