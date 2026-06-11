"""Role lens — turns the *same* search query into role-tailored intelligence.

Four personas use PharmaWatch with very different jobs-to-be-done:

- **pharmacist** — dispensing & patient safety at the counter: stock / shortages,
  side effects, dosage, OTC counseling. Cares about local (BE) availability and
  pharmacovigilance signals first.
- **marketing** — campaign & brand-communications team: reach & engagement,
  social buzz, sentiment, content channels, message resonance and promotions.
- **brand_manager** — strategic brand owner at a pharma lab: market share &
  competitive positioning, demand trends, launch readiness, pricing/reimbursement,
  clinical evidence used for positioning, and brand risk.
- **admin** — balanced full view; can additionally *view as* any persona.

The lens never *hides* sources (that was a deliberate product decision — see the
"re-rank + AI lens" approach): every role still sees everything, but results are
re-ranked toward their domain and the AI answer is rewritten through their lens.

This module is the single source of truth shared by the live / ai / semantic
search routers and surfaced to the frontend via `role_label` / `ROLE_LABELS`.
"""
from __future__ import annotations

from typing import Dict, Optional

from models.user import User, UserRole

# Canonical role keys. Kept as plain strings so they round-trip cleanly through
# query params, JSON responses and the audit column without enum coupling.
PHARMACIST = "pharmacist"
MARKETING = "marketing"
BRAND_MANAGER = "brand_manager"
ADMIN = "admin"

VALID_ROLES = {PHARMACIST, MARKETING, BRAND_MANAGER, ADMIN}

ROLE_LABELS: Dict[str, str] = {
    PHARMACIST: "Pharmacist",
    MARKETING: "Marketing",
    BRAND_MANAGER: "Brand Manager",
    ADMIN: "Admin (full view)",
}

# Short, human description of what each lens prioritises — shown in the UI banner.
ROLE_FOCUS: Dict[str, str] = {
    PHARMACIST: "Availability & shortages, side effects, dosage and OTC counseling.",
    MARKETING: "Reach & engagement, social buzz, sentiment and message resonance.",
    BRAND_MANAGER: "Market share, competitive positioning, demand trends, launch & brand risk.",
    ADMIN: "Balanced full view across every source and topic.",
}

# ── Relevance tiers (NO numeric score) ──────────────────────────────────────────
# The old design multiplied a source boost × topic boost × an engagement factor and
# sorted on that float. In practice the engagement factor (e.g. a YouTube video's
# view count) dominated the product, so every role got the *same* ordering — the
# role lens was invisible. We replaced it with deterministic PRIORITY TIERS:
#
#   each role declares, in priority order, the source categories and topic
#   categories it cares about. A result lands in the lowest-numbered (= highest
#   priority) tier it matches. Ordering is then a pure tuple comparison —
#   (risk first, source tier, topic tier, freshness) — with NO score and NO
#   engagement in the ordering at all.
#
# This makes the role lens both *visible* (a pharmacist's official safety/supply
# sources genuinely come first) and *explainable* (you can name the tier a result
# fell into). Tiers are ordered lists; membership is by exact source_type / topic.
# Anything unlisted falls to _OTHER_TIER. Admin uses empty tiers → everything is
# tier 0, so admin ordering collapses to pure freshness (a balanced, neutral view).

# Sentinel tier for sources/topics a role didn't rank. Higher number = lower
# priority, so unranked items sink below everything the role explicitly named,
# but stay above nothing else (they're still shown — the lens never hides).
_OTHER_TIER = 9

# Per role: ordered tiers of source_types. Index in the list == priority tier.
_SOURCE_TIERS: Dict[str, list] = {
    PHARMACIST: [
        # T0 — official safety & supply: the dispensing counter's first read
        {"belgium_health", "fagg_shortage", "ansm_shortage", "ansm_safety", "ansm", "eudravigilance", "safety_gate"},
        # T1 — clinical evidence & regulated patient info
        {"openfda", "pubmed", "bcfi_cbip", "belgium_hcp", "data_gov_be"},
        # T2 — lived patient experience
        {"doctissimo", "forum", "app_store", "reddit", "clinical_trials"},
        # T3 — general reference / reach (least relevant to dispensing)
        {"wikipedia", "news", "google_trends", "youtube"},
    ],
    MARKETING: [
        # T0 — reach, engagement & buzz: where campaign signal actually lives
        {"youtube", "google_trends", "reddit", "news"},
        # T1 — consumer voice / reviews
        {"app_store", "forum", "doctissimo"},
        # T2 — reputational-risk watch & reference
        {"eudravigilance", "wikipedia", "safety_gate"},
        # T3 — clinical/regulatory (secondary for campaigns)
        {"belgium_health", "pubmed", "clinical_trials", "openfda", "ansm", "ansm_safety", "bcfi_cbip"},
    ],
    BRAND_MANAGER: [
        # T0 — market / competitive / demand signal
        {"news", "google_trends"},
        # T1 — reach + evidence for positioning
        {"youtube", "pubmed", "clinical_trials", "reddit", "eudravigilance"},
        # T2 — supply / reimbursement / reputation → market shifts
        {"fagg_shortage", "ansm_shortage", "ansm_safety", "ansm", "bcfi_cbip",
         "belgium_health", "wikipedia", "app_store", "forum", "doctissimo", "openfda"},
    ],
    ADMIN: [],  # neutral: no source priority → order by freshness only
}

# Per role: ordered tiers of topics. Index == priority tier.
_TOPIC_TIERS: Dict[str, list] = {
    PHARMACIST: [
        {"availability", "side_effect"},   # T0 — supply & safety
        {"efficacy", "recommendation"},    # T1 — clinical use
        {"price", "general"},              # T2
    ],
    MARKETING: [
        {"recommendation", "price"},       # T0 — advocacy & promo resonance
        {"efficacy", "general"},           # T1 — claim resonance / buzz
        {"side_effect", "availability"},   # T2 — reputational watch
    ],
    BRAND_MANAGER: [
        {"efficacy", "recommendation", "price"},  # T0 — positioning & pricing
        {"availability", "side_effect"},          # T1 — supply & brand risk
        {"general"},                              # T2
    ],
    ADMIN: [],  # neutral
}


def _tier_of(tiers: list, value: Optional[str]) -> int:
    """Index of the first tier set containing `value`, else _OTHER_TIER."""
    v = (value or "").lower()
    for i, members in enumerate(tiers):
        if v in members:
            return i
    return _OTHER_TIER

# ── AI synthesis lenses ─────────────────────────────────────────────────────────
# Appended to the AI system prompt so the narrative is written for the persona.
#
# Each lens turns the AI answer into role-specific *market analytics for Belgium
# (primary) and France (secondary)* about the queried product / brand — the core
# product promise: "what is going on in my country regarding my product/brand?".
# Every lens should localise to BE/FR (mention region, language community FR/NL/DE,
# and local brand names e.g. Dafalgan/Doliprane) and prefer the most recent signal.
_ROLE_PROMPT: Dict[str, str] = {
    PHARMACIST: (
        "AUDIENCE LENS — COMMUNITY PHARMACIST (dispensing counter, Belgium first, "
        "France second):\n"
        "Answer as operational intelligence for a pharmacist serving Belgian (and "
        "French) patients. Lead with what affects dispensing and patient safety RIGHT "
        "NOW in this market: Belgian stock / shortage status (FAGG/AFMPS, ANSM for FR) "
        "and concrete substitutes available locally, reported side effects and "
        "adverse-reaction signals, correct dosage/administration, contraindications, "
        "reimbursement/INAMI status when relevant, and concise OTC counseling points "
        "to relay to a patient. Use local brand names (e.g. Dafalgan, Doliprane). "
        "Treat marketing/brand-buzz as secondary. Be practical and clinically cautious; "
        "never give a definitive medical determination — flag, don't diagnose."
    ),
    MARKETING: (
        "AUDIENCE LENS — PHARMA MARKETING / BRAND COMMUNICATIONS (Belgium first, "
        "France second):\n"
        "Answer as audience & campaign analytics for a marketing team watching this "
        "product/brand in Belgium (FR/NL/DE communities) and France. Lead with: how "
        "the public is talking about it and the sentiment trend, share-of-voice and "
        "reach across channels (video, social, news, forums), engagement and which "
        "messages/claims resonate vs. fall flat, emerging buzz, creators/influencers "
        "and seasonal demand spikes, and concrete campaign/content/channel "
        "opportunities for this market. Localise by language community and region. "
        "Treat clinical/regulatory detail as secondary, but flag reputational risk "
        "early. Frame everything as it informs campaign, channel and content decisions."
    ),
    BRAND_MANAGER: (
        "AUDIENCE LENS — PHARMA BRAND MANAGER (Belgium first, France second, market "
        "strategy):\n"
        "Answer as strategic brand intelligence for the owner of this product's "
        "commercial strategy in Belgium and France. Lead with the market read: "
        "competitive positioning and share-of-voice vs. named local competitors, "
        "demand trends and momentum, pricing and reimbursement (INAMI/RIZIV, ameli) "
        "context, supply/availability shifts that open or threaten share, the clinical "
        "evidence that supports positioning, and brand risk. Localise to the BE/FR "
        "market and call out per-country differences. Frame insights as they inform "
        "launch, lifecycle, portfolio and competitive decisions — think share, growth "
        "and defensibility, not campaign mechanics."
    ),
    ADMIN: (
        "AUDIENCE LENS — ADMIN (full balanced view, Belgium + France):\n"
        "Give a balanced market overview covering the dispensing/safety angle, the "
        "marketing/audience angle and the brand-strategy angle, without favouring any "
        "single persona. Localise to Belgium (primary) and France (secondary)."
    ),
}


def lens_prompt(role: str) -> str:
    """Return the persona block to append to the AI system prompt."""
    return _ROLE_PROMPT.get(role, _ROLE_PROMPT[ADMIN])


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, ROLE_LABELS[ADMIN])


def resolve_role(current_user: Optional[User], requested: Optional[str]) -> str:
    """Decide which lens to apply.

    - Admins may *view as* any of the three roles via `requested` (the UI switcher).
    - Non-admins are locked to their own account role; a `requested` override that
      doesn't match their role is ignored (no privilege escalation, no error).
    - Falls back to the user's own role, then to admin/neutral when unknown.
    """
    own = None
    if current_user is not None and getattr(current_user, "role", None) is not None:
        own = current_user.role.value if isinstance(current_user.role, UserRole) else str(current_user.role)

    req = (requested or "").strip().lower()
    req = req if req in VALID_ROLES else None

    if own == ADMIN:
        # Admin: honour the requested view-as lens, else default to balanced admin.
        return req or ADMIN
    if own in VALID_ROLES:
        # Non-admin: always own role, regardless of what was requested.
        return own
    # Unknown / unauthenticated — neutral.
    return ADMIN


def role_tier(role: str, source_type: Optional[str], topic: Optional[str]) -> tuple:
    """Return (source_tier, topic_tier) for a result under this role's lens.

    Lower numbers = higher priority. No score, no engagement — just which
    category the source/topic falls into for this persona. Unranked → _OTHER_TIER.
    """
    src_tiers = _SOURCE_TIERS.get(role, [])
    top_tiers = _TOPIC_TIERS.get(role, [])
    return (_tier_of(src_tiers, source_type), _tier_of(top_tiers, topic))


def _recency_value(published_at) -> float:
    """Sortable freshness: newer → larger. Missing date → 0.0 (sinks to bottom
    of its tier, below anything dated)."""
    if published_at is None:
        return 0.0
    try:
        return published_at.timestamp()
    except Exception:
        return 0.0


def role_sort_key(
    role: str,
    source_type: Optional[str],
    topic: Optional[str],
    is_risk: bool = False,
    published_at=None,
) -> tuple:
    """Ascending sort key for role-aware ordering (use `sorted(..., key=...)`,
    NO reverse). Tuple ordering, no numeric score:

        (role-relevant risk first, source tier, topic tier, newest first)

    The lens is *opinionated*: a risk does not float to #1 for everyone. Patient-
    safety roles (pharmacist, and the neutral admin view) put any risk first — a
    shortage or side-effect is their job. Market-facing roles (brand_manager,
    marketing) do NOT force risk to the top; their own source/topic tiers decide,
    so the SAME shortage that is #1 for a pharmacist ranks *secondary* for a brand
    manager (behind market/demand signal) and low for marketing. That makes the
    ordering genuinely different per role on the same query, not just the layout.
    """
    src_tier, top_tier = role_tier(role, source_type, topic)
    risk_first = is_risk and role in (PHARMACIST, ADMIN)
    return (0 if risk_first else 1, src_tier, top_tier, -_recency_value(published_at))


def grounding_sort_key(role: str, source_type: Optional[str], topic: Optional[str] = None) -> tuple:
    """Ascending ordering key for AI grounding sources (no risk/recency signal):
    just the role's (source tier, topic tier) so the most role-relevant sources
    occupy the low [n] citation indices."""
    return role_tier(role, source_type, topic)
