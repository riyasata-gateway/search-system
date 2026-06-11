"""Per-search feature engineering — turns a raw result set into role-tailored
metrics that auto-fill the dashboard the moment a search returns.

This is the single source of truth for "metrics about the search you just ran"
(distinct from `api/routers/search_analytics.py`, which aggregates the *historical*
audit log). It is a pure function over a normalised list of result dicts, so it
works identically for live and semantic search and is trivially unit-testable.

See SEARCH_METRICS_DESIGN.md for the data model, linkable-field rationale and the
role→KPI mapping.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from core.role_lens import ADMIN, BRAND_MANAGER, MARKETING, PHARMACIST, role_label

# ── source taxonomy (shared with the role lens' intent) ─────────────────────────
# Authoritative / regulated / clinical sources → "official coverage" + authority mix.
OFFICIAL_SOURCES = {
    "belgium_health", "fagg_shortage", "ansm", "ansm_shortage", "ansm_safety",
    "eudravigilance", "bcfi_cbip", "pubmed", "clinical_trials", "openfda",
    "belgium_hcp", "data_gov_be",
}
# Social / consumer channels → buzz & reach.
SOCIAL_SOURCES = {"youtube", "reddit", "forum", "app_store", "doctissimo"}

_TOP_N = 8


# ── output schema ───────────────────────────────────────────────────────────────
class Slice(BaseModel):
    label: str
    count: int
    value: Optional[float] = None   # secondary measure (e.g. reach, pct) when relevant


class KpiCard(BaseModel):
    key: str
    label: str
    value: str
    sub: Optional[str] = None
    tone: Optional[str] = None      # "good" | "warn" | "danger" | None


class TimePoint(BaseModel):
    date: str
    count: int
    positive: int
    neutral: int
    negative: int


class CrossRow(BaseModel):
    label: str
    positive: int
    neutral: int
    negative: int
    total: int


class SearchMetrics(BaseModel):
    role: str
    role_label: str
    total: int
    # headline cards, ordered, role-specific
    headline: List[KpiCard]
    # shared engineered scalars
    sentiment_index: float
    net_sentiment_label: str
    reach_total: int
    engagement_rate: float
    risk_share: float
    official_coverage: float
    source_diversity: int
    # breakdowns (for charts)
    sentiment_mix: List[Slice]
    topic_mix: List[Slice]
    source_mix: List[Slice]          # by volume
    channel_reach: List[Slice]       # by engagement (share of voice)
    geo_mix: List[Slice]
    language_mix: List[Slice]
    risk_mix: List[Slice]            # risk_type != none only
    timeline: List[TimePoint]
    # linked cross-tabs
    sentiment_by_topic: List[CrossRow]
    risk_by_source: List[Slice]


# ── helpers ─────────────────────────────────────────────────────────────────────
def _slices(counter: Counter, *, top: int = _TOP_N) -> List[Slice]:
    return [Slice(label=str(k), count=int(v))
            for k, v in counter.most_common(top)]


def _pct(n: int, d: int) -> float:
    return round(n / d, 4) if d else 0.0


def _net_label(index: float, pos: int, neg: int, total: int) -> str:
    # Polarised (both poles material) → Mixed, regardless of the net.
    if total and pos / total >= 0.2 and neg / total >= 0.2:
        return "Mixed"
    if index > 0.15:
        return "Positive"
    if index < -0.15:
        return "Negative"
    return "Neutral"


def _as_date(published_at: Any) -> Optional[str]:
    if published_at is None:
        return None
    if isinstance(published_at, datetime):
        return published_at.date().isoformat()
    if isinstance(published_at, str) and len(published_at) >= 10:
        return published_at[:10]
    return None


def _fmt_int(n: int) -> str:
    return f"{n:,}"


# ── headline KPI builders per role ──────────────────────────────────────────────
def _headline(role: str, *, total: int, pos: int, neg: int, neu: int,
              sentiment_index: float, net_label: str, reach_total: int,
              engagement_rate: float, risk_share: float, official_coverage: float,
              source_diversity: int, topic_ct: Counter, risk_ct: Counter,
              channel_reach: List[Slice], geo_ct: Counter) -> List[KpiCard]:
    side_effect = topic_ct.get("side_effect", 0)
    availability = topic_ct.get("availability", 0)
    recommendation = topic_ct.get("recommendation", 0)
    ae = risk_ct.get("adverse_event", 0)
    shortage = risk_ct.get("shortage", 0)
    misinfo = risk_ct.get("misinformation", 0)
    idx_str = f"{sentiment_index:+.2f}"

    if role == PHARMACIST:
        return [
            KpiCard(key="safety", label="Safety signals", value=_fmt_int(ae),
                    sub="adverse-event flags", tone="danger" if ae else "good"),
            KpiCard(key="supply", label="Supply signals", value=_fmt_int(shortage + availability),
                    sub=f"{shortage} shortage · {availability} availability",
                    tone="warn" if (shortage + availability) else None),
            KpiCard(key="official", label="Official coverage", value=f"{official_coverage*100:.0f}%",
                    sub="from regulated sources",
                    tone="good" if official_coverage >= 0.3 else "warn"),
            KpiCard(key="side_effect", label="Side-effect chatter", value=_fmt_int(side_effect),
                    sub="mentions", tone="warn" if side_effect else None),
            KpiCard(key="risk", label="Risk share", value=f"{risk_share*100:.0f}%",
                    sub="of results flagged", tone="danger" if risk_share > 0.1 else None),
        ]
    if role == MARKETING:
        top_channel = channel_reach[0] if channel_reach else None
        sov = ""
        if top_channel and reach_total:
            sov = f"{(top_channel.value or 0)/reach_total*100:.0f}% of reach"
        return [
            KpiCard(key="reach", label="Total reach", value=_fmt_int(reach_total),
                    sub="audience exposure"),
            KpiCard(key="sov", label="Top channel",
                    value=top_channel.label if top_channel else "—", sub=sov or "share of voice"),
            KpiCard(key="eng_rate", label="Engagement rate", value=_fmt_int(int(engagement_rate)),
                    sub="avg reach / mention"),
            KpiCard(key="sentiment", label="Net sentiment", value=net_label,
                    sub=f"index {idx_str}",
                    tone="good" if sentiment_index > 0.15 else "danger" if sentiment_index < -0.15 else None),
            KpiCard(key="advocacy", label="Advocacy", value=_fmt_int(recommendation),
                    sub="recommendation mentions", tone="good" if recommendation else None),
        ]
    if role == BRAND_MANAGER:
        be = geo_ct.get("BE", 0)
        fr = geo_ct.get("FR", 0)
        return [
            KpiCard(key="sentiment", label="Net sentiment", value=idx_str,
                    sub=net_label,
                    tone="good" if sentiment_index > 0.15 else "danger" if sentiment_index < -0.15 else None),
            KpiCard(key="risk", label="Risk exposure", value=f"{risk_share*100:.0f}%",
                    sub="brand-risk share", tone="danger" if risk_share > 0.1 else None),
            KpiCard(key="geo", label="BE vs FR",
                    value=f"{be}:{fr}", sub="mention split"),
            KpiCard(key="authority", label="Authority mix", value=f"{official_coverage*100:.0f}%",
                    sub="clinical / regulatory"),
            KpiCard(key="misinfo", label="Misinformation", value=_fmt_int(misinfo),
                    sub="reputational watch", tone="danger" if misinfo else None),
        ]
    # admin — balanced
    return [
        KpiCard(key="total", label="Mentions", value=_fmt_int(total), sub="this search"),
        KpiCard(key="sentiment", label="Net sentiment", value=idx_str, sub=net_label,
                tone="good" if sentiment_index > 0.15 else "danger" if sentiment_index < -0.15 else None),
        KpiCard(key="risk", label="Risk share", value=f"{risk_share*100:.0f}%",
                sub="of results flagged", tone="danger" if risk_share > 0.1 else None),
        KpiCard(key="diversity", label="Source diversity", value=_fmt_int(source_diversity),
                sub="distinct channels"),
        KpiCard(key="reach", label="Total reach", value=_fmt_int(reach_total), sub="audience exposure"),
    ]


# ── main entry point ─────────────────────────────────────────────────────────────
def compute_metrics(items: List[Dict[str, Any]], role: str) -> SearchMetrics:
    """Feature-engineer role-tailored metrics from a result set.

    `items` is a list of dicts with (any subset of) keys:
        source_type, country, language, published_at, sentiment, topic,
        risk_type, engagement
    Missing values degrade gracefully (e.g. semantic search has no engagement).
    """
    role = role if role in {PHARMACIST, MARKETING, BRAND_MANAGER, ADMIN} else ADMIN
    total = len(items)

    sent_ct: Counter = Counter()
    topic_ct: Counter = Counter()
    src_ct: Counter = Counter()
    geo_ct: Counter = Counter()
    lang_ct: Counter = Counter()
    risk_ct: Counter = Counter()
    reach_by_channel: Dict[str, int] = defaultdict(int)
    risk_by_source: Dict[str, int] = defaultdict(int)
    sent_by_topic: Dict[str, Counter] = defaultdict(Counter)
    timeline_map: Dict[str, Dict[str, int]] = {}

    reach_total = 0
    risk_count = 0
    official = 0

    for it in items:
        s = (it.get("sentiment") or "neutral").lower()
        t = (it.get("topic") or "general").lower()
        st = (it.get("source_type") or "other").lower()
        c = it.get("country") or "—"
        lng = it.get("language") or "—"
        rt = (it.get("risk_type") or "none").lower()
        eng = int(it.get("engagement") or 0)

        sent_ct[s] += 1
        topic_ct[t] += 1
        src_ct[st] += 1
        geo_ct[c] += 1
        lang_ct[lng] += 1
        sent_by_topic[t][s] += 1
        reach_total += eng
        reach_by_channel[st] += eng
        if st in OFFICIAL_SOURCES:
            official += 1
        if rt and rt != "none":
            risk_ct[rt] += 1
            risk_count += 1
            risk_by_source[st] += 1

        d = _as_date(it.get("published_at"))
        if d:
            b = timeline_map.setdefault(d, {"count": 0, "positive": 0, "neutral": 0, "negative": 0})
            b["count"] += 1
            if s in b:
                b[s] += 1

    pos = sent_ct.get("positive", 0)
    neg = sent_ct.get("negative", 0)
    neu = sent_ct.get("neutral", 0)
    sentiment_index = round((pos - neg) / total, 3) if total else 0.0
    net_label = _net_label(sentiment_index, pos, neg, total)
    engagement_rate = round(reach_total / total, 1) if total else 0.0
    risk_share = _pct(risk_count, total)
    official_coverage = _pct(official, total)
    source_diversity = len(src_ct)

    # channel reach (share of voice) — by engagement, fall back to volume.
    if reach_total > 0:
        channel_reach = [Slice(label=k, count=src_ct[k], value=float(v))
                         for k, v in sorted(reach_by_channel.items(),
                                            key=lambda kv: kv[1], reverse=True)[:_TOP_N] if v > 0]
    else:
        channel_reach = [Slice(label=s.label, count=s.count, value=float(s.count))
                         for s in _slices(src_ct)]

    # linked cross-tabs
    sentiment_by_topic = [
        CrossRow(label=tp, positive=cc.get("positive", 0), neutral=cc.get("neutral", 0),
                 negative=cc.get("negative", 0),
                 total=cc.get("positive", 0) + cc.get("neutral", 0) + cc.get("negative", 0))
        for tp, cc in sorted(sent_by_topic.items(),
                             key=lambda kv: sum(kv[1].values()), reverse=True)[:_TOP_N]
    ]
    risk_by_source_slices = [Slice(label=k, count=int(v))
                             for k, v in sorted(risk_by_source.items(),
                                                key=lambda kv: kv[1], reverse=True)[:_TOP_N]]

    timeline = [TimePoint(date=d, count=v["count"], positive=v["positive"],
                          neutral=v["neutral"], negative=v["negative"])
                for d, v in sorted(timeline_map.items())]

    headline = _headline(
        role, total=total, pos=pos, neg=neg, neu=neu,
        sentiment_index=sentiment_index, net_label=net_label, reach_total=reach_total,
        engagement_rate=engagement_rate, risk_share=risk_share,
        official_coverage=official_coverage, source_diversity=source_diversity,
        topic_ct=topic_ct, risk_ct=risk_ct, channel_reach=channel_reach, geo_ct=geo_ct,
    )

    return SearchMetrics(
        role=role,
        role_label=role_label(role),
        total=total,
        headline=headline,
        sentiment_index=sentiment_index,
        net_sentiment_label=net_label,
        reach_total=reach_total,
        engagement_rate=engagement_rate,
        risk_share=risk_share,
        official_coverage=official_coverage,
        source_diversity=source_diversity,
        sentiment_mix=_slices(sent_ct),
        topic_mix=_slices(topic_ct),
        source_mix=_slices(src_ct),
        channel_reach=channel_reach,
        geo_mix=_slices(geo_ct),
        language_mix=_slices(lang_ct),
        risk_mix=[Slice(label=k, count=int(v)) for k, v in risk_ct.most_common(_TOP_N)],
        timeline=timeline,
        sentiment_by_topic=sentiment_by_topic,
        risk_by_source=risk_by_source_slices,
    )


class SearchIntelligence(BaseModel):
    """Combined two-tier metrics returned with a search and persisted per query:
    the always-present snapshot plus the corpus-based DIA framework metrics for
    the resolved brand (null when the query doesn't resolve to a known brand)."""
    role: str
    role_label: str
    mode: str
    brand_resolved: bool
    brand_id: Optional[int] = None
    brand_name: Optional[str] = None
    headline: List[KpiCard]            # combined role headline (framework + snapshot)
    snapshot: SearchMetrics
    framework: Optional[dict] = None   # {"bundles": {...}, "scalars": {...}}
