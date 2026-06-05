/**
 * Plain-language, one-line definitions for the KPIs and composite scores shown
 * across the brand dashboards. Surfaced via the <InfoTip> icon next to each KPI
 * so a number is never unexplained. Keep these jargon-free and customer-facing —
 * they describe *what the metric means and why it matters*, not how it's computed.
 */
export const GLOSSARY: Record<string, string> = {
  // ── Composite scores ──────────────────────────────────────────────────────
  "Brand Potential Index":
    "A 0–100 read on how much headroom a brand has to grow, blending awareness, adoption, sentiment and category fit.",
  "Launch Readiness":
    "A 0–100 go/no-go score for a launch or push, combining early demand, buzz, sentiment and (when connected) distribution.",
  "Demand Momentum":
    "The rate of change in interest and mentions — whether attention is speeding up or slowing down (0 = fading, 100 = surging). A leading indicator of where demand is heading.",
  "Risk Mentions":
    "Count of mentions flagged as a safety, quality or reputational risk in the period — your watch-list.",
  "Total Reach":
    "Total mentions of the brand across all monitored sources — the size of the conversation.",
  "Positive Sentiment":
    "Share of mentions that read as positive — the headline mood toward the brand.",

  // ── BPI components ─────────────────────────────────────────────────────────
  "Awareness": "How widely the brand is talked about vs its category — its share of category mentions.",
  "Adoption": "Whether people are actually buying/using the brand, not just discussing it: its share of pharmacy sell-out vs category peers. With no sell-out feed connected, it falls back to a proxy (purchase-intent + review + recommendation mentions).",
  "Sentiment": "Net positivity of the conversation about the brand (engagement-weighted).",
  "Fit": "How well the brand resonates inside its own category — its share of the category's conversation, not inflated by off-category buzz.",
  "Market fit": "How well the brand resonates inside its own category — its share of the category's conversation, not inflated by off-category buzz.",

  // ── Launch-readiness components ───────────────────────────────────────────
  "Safety clearance": "A 0–100 'safe to amplify?' gate = 100 − negative-review share − risk-flagged share. Drops when there's an active adverse-event or negative signal.",
  "Freshness": "How recent the underlying data is: 100 if there's a mention in the last ~14 days, decaying to 0 by ~180 days. Low means the score rests on stale data.",

  // ── Brand Potential modules ───────────────────────────────────────────────
  "Lifecycle":
    "Where the brand sits in its life stage (emerging, growing, mature, declining) based on attention dynamics.",
  "Key Message Tuning":
    "Which themes resonate (winning) vs fall flat (losing) with the audience, so messaging can be sharpened.",
  "Campaign Pivots":
    "Signal-triggered prompts to change creative or spend when the data shifts under a campaign.",
  "HCP Targeting":
    "Prescriber momentum for prioritising healthcare-professional outreach (requires an Rx/KOL data feed).",
  "Next-Best-Action":
    "A prioritised, evidence-backed to-do queue composed across every signal, weighted by what's worked before.",
  "Message Resonance":
    "Which topics land with audiences and which don't, scored from engagement-weighted mentions.",
};

export const define = (key: string): string => GLOSSARY[key] ?? "";
