"""Source-class taxonomy — what a source's date/content actually *means*.

A mention's date means very different things by source, so the time-series
DEMAND / RECENCY engines (momentum, freshness, anomaly) must only count genuine
consumer-event sources. Literature carries journal-issue dates; reference/
regulatory data is stamped at collection (`now()`), so it would otherwise make a
brand look permanently "fresh" or spike its "demand momentum" with no real demand.

  • DEMAND   — real consumer/public events with genuine dates → drive momentum /
               freshness / anomaly (and the consumer-reach side of BPI).
  • EVIDENCE — issue-dated literature → power evidence/claims KPIs only.
  • REFERENCE— catalog / regulatory snapshots (collection-stamped, no event date)
               → power safety / catalog / ATC KPIs only.

Anything not listed is treated conservatively as NON-demand (REFERENCE), so a new
source can't silently leak into the demand signal.
"""

DEMAND_SOURCE_TYPES = frozenset({
    "farmaline", "medimarket",          # pharmacy product reviews
    "trustpilot", "carenity",           # pharmacy + drug-level reviews
    "rss", "news",                      # news / press
    "youtube", "forum", "doctissimo", "reddit", "app_store",
    "google_trends",                    # search interest
})

# First-person consumer/patient OPINION — the only sources whose sentiment is a
# real *perception* signal. A subset of DEMAND: it excludes news/press (corporate
# articles aren't patient opinion) and search interest (google_trends has no
# polarity). Sentiment / complaint-rate KPIs must be scoped to THIS set, or a
# distributor with only press coverage (e.g. an M&A or IPO article classified
# "negative") would surface a meaningless "patient sentiment".
OPINION_SOURCE_TYPES = frozenset({
    "farmaline", "medimarket", "app_store",   # product reviews
    "trustpilot", "carenity",                 # pharmacy + drug-level reviews
    "youtube", "forum", "doctissimo", "reddit",  # conversational social
})

EVIDENCE_SOURCE_TYPES = frozenset({
    "pubmed", "clinical_trials",
})

REFERENCE_SOURCE_TYPES = frozenset({
    "bcfi", "bcfi_cbip", "eudravigilance", "openfda", "safety_gate",
    "ansm", "ansm_shortage", "belgium_health", "fagg_shortage", "wikipedia",
    "brand_site",                       # brand-owned, collection-stamped — not a demand event
})

# Sources that must NOT drive demand/recency engines (everything non-demand).
NON_DEMAND_SOURCE_TYPES = EVIDENCE_SOURCE_TYPES | REFERENCE_SOURCE_TYPES

# Free-text news/social searched by trade name — namesake-prone, so a bare brand
# name match here must be backed by a pharma/health signal before it attributes
# (see processing.brand_match.has_health_context). Review sources are excluded:
# a genuine review may carry no pharma vocabulary yet is correctly attributed by
# the pharmacy/store it was scraped from.
NAMESAKE_GATED_SOURCE_TYPES = frozenset({
    "rss", "news", "youtube", "forum", "doctissimo", "reddit", "wikipedia",
})


def is_demand_source(source_type: str | None) -> bool:
    return (source_type or "") in DEMAND_SOURCE_TYPES


def is_opinion_source(source_type: str | None) -> bool:
    return (source_type or "") in OPINION_SOURCE_TYPES