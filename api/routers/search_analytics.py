"""Search analytics — turns the search-audit log into role-scoped intelligence.

Every `/search/*` call is persisted to `search_queries` / `search_results` /
`ai_answers` with the role lens stamped on the query row. This router reads that
log back and aggregates it into the metrics each persona actually cares about:

- **demand signal** — what is being searched, how often, and what's trending
- **coverage blind spots** — queries that returned zero results (= data we're missing)
- **sentiment / topic / source / geo mix** of everything the searches surfaced
- **risk exposure** — share of results flagged as adverse-event / shortage / etc.
- **operational health** — latency, AI vs live vs semantic usage

Authority model (mirrors `core/role_lens.resolve_role`):
- **admins** see every role and can filter to one via the `?role=` dropdown
  (or `role=all` / omitted for the combined view);
- **non-admins are locked to their own role** — they can't inspect another
  persona's search behaviour.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Date, Integer, case, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from core.config import settings
from core.database import get_db
from core.role_lens import ADMIN, ROLE_FOCUS, ROLE_LABELS, VALID_ROLES
from models.mention import Mention, MentionClassification, Sentiment
from models.search_audit import SearchMode, SearchQuery, SearchResult
from models.user import User, UserRole

router = APIRouter()

# Period token → lookback window. `all` means no lower bound.
_PERIODS: Dict[str, Optional[int]] = {"7d": 7, "30d": 30, "90d": 90, "180d": 180, "365d": 365, "all": None}


def _period_start(period: str) -> Optional[datetime]:
    days = _PERIODS.get(period, 30)
    if days is None:
        return None
    return datetime.now(timezone.utc) - timedelta(days=days)


def _resolve_scope(user: User, requested: Optional[str]) -> Tuple[Optional[str], str]:
    """Return (role_filter, scope_label).

    role_filter == None means "all roles" (admin combined view). A concrete role
    string means filter `search_queries.role` to it. Non-admins are forced to
    their own role regardless of `requested`.
    """
    own = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    req = (requested or "").strip().lower()

    if own == ADMIN:
        if req in VALID_ROLES:
            return req, ROLE_LABELS.get(req, req)
        return None, "All roles"
    # Non-admin: locked to own role.
    return own, ROLE_LABELS.get(own, own)


class Kpis(BaseModel):
    total_searches: int
    unique_queries: int
    avg_results: float
    zero_result_rate: float          # 0..1
    avg_latency_ms: float
    risk_result_share: float         # 0..1 of result rows flagged as a risk
    live_searches: int
    ai_searches: int
    semantic_searches: int


class TimelinePoint(BaseModel):
    date: str
    searches: int
    positive: int
    neutral: int
    negative: int


class QueryStat(BaseModel):
    q: str
    count: int
    avg_results: float
    last_searched: Optional[datetime]


class Slice(BaseModel):
    label: str
    count: int


class AnalyticsDashboard(BaseModel):
    scope: str                       # role key or "all"
    scope_label: str
    period: str
    generated_at: datetime
    kpis: Kpis
    timeline: List[TimelinePoint]
    top_queries: List[QueryStat]
    zero_result_queries: List[QueryStat]
    sentiment: List[Slice]
    topics: List[Slice]
    sources: List[Slice]
    geo: List[Slice]
    risk: List[Slice]


class RoleUsageItem(BaseModel):
    role: str
    role_label: str
    total_searches: int
    unique_queries: int
    avg_results: float
    zero_result_rate: float
    risk_result_share: float


def _query_filter(role_filter: Optional[str], start: Optional[datetime]):
    conds = []
    if role_filter is not None:
        conds.append(SearchQuery.role == role_filter)
    if start is not None:
        conds.append(SearchQuery.created_at >= start)
    return conds


@router.get("/dashboard", response_model=AnalyticsDashboard)
async def analytics_dashboard(
    role: Optional[str] = Query(None, description="Role to scope to (admins only; pharmacist/marketing/brand_manager/admin or 'all')"),
    period: str = Query("30d", description="7d | 30d | 90d | 180d | 365d | all"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role_filter, scope_label = _resolve_scope(current_user, role)
    start = _period_start(period)
    qconds = _query_filter(role_filter, start)

    # Subquery of the query ids in scope — reused to scope result-row aggregations.
    scoped_ids = select(SearchQuery.id).where(*qconds) if qconds else select(SearchQuery.id)

    # ── KPIs over search_queries ────────────────────────────────────────────
    kpi_select = select(
        func.count(SearchQuery.id),
        func.count(distinct(func.lower(SearchQuery.q))),
        func.coalesce(func.avg(SearchQuery.total_results), 0),
        func.coalesce(func.avg(SearchQuery.elapsed_ms), 0),
    )
    kpi_row = (await db.execute(kpi_select.where(*qconds) if qconds else kpi_select)).one()
    total_searches = int(kpi_row[0] or 0)
    unique_queries = int(kpi_row[1] or 0)
    avg_results = round(float(kpi_row[2] or 0), 2)
    avg_latency = round(float(kpi_row[3] or 0), 1)

    # zero-result count (coverage blind-spot rate)
    zero_count = int((await db.execute(
        select(func.count(SearchQuery.id)).where(*qconds, SearchQuery.total_results == 0)
        if qconds else
        select(func.count(SearchQuery.id)).where(SearchQuery.total_results == 0)
    )).scalar() or 0)
    zero_rate = round(zero_count / total_searches, 4) if total_searches else 0.0

    # per-mode counts
    mode_rows = (await db.execute(
        select(SearchQuery.mode, func.count(SearchQuery.id)).where(*qconds).group_by(SearchQuery.mode)
        if qconds else
        select(SearchQuery.mode, func.count(SearchQuery.id)).group_by(SearchQuery.mode)
    )).all()
    mode_counts = {m: c for m, c in mode_rows}
    live_n = int(mode_counts.get(SearchMode.live, 0))
    ai_n = int(mode_counts.get(SearchMode.ai, 0))
    sem_n = int(mode_counts.get(SearchMode.semantic, 0))

    # ── risk share over result rows ─────────────────────────────────────────
    total_results_rows = int((await db.execute(
        select(func.count(SearchResult.id)).where(SearchResult.query_id.in_(scoped_ids))
    )).scalar() or 0)
    risk_rows = int((await db.execute(
        select(func.count(SearchResult.id)).where(
            SearchResult.query_id.in_(scoped_ids),
            SearchResult.risk_type.isnot(None),
            SearchResult.risk_type != "none",
        )
    )).scalar() or 0)
    risk_share = round(risk_rows / total_results_rows, 4) if total_results_rows else 0.0

    kpis = Kpis(
        total_searches=total_searches,
        unique_queries=unique_queries,
        avg_results=avg_results,
        zero_result_rate=zero_rate,
        avg_latency_ms=avg_latency,
        risk_result_share=risk_share,
        live_searches=live_n,
        ai_searches=ai_n,
        semantic_searches=sem_n,
    )

    # ── timeline: searches/day + result sentiment/day ───────────────────────
    day = cast(SearchQuery.created_at, Date)
    search_day_rows = (await db.execute(
        select(day.label("d"), func.count(SearchQuery.id)).where(*qconds).group_by(day).order_by(day)
        if qconds else
        select(day.label("d"), func.count(SearchQuery.id)).group_by(day).order_by(day)
    )).all()
    sent_day_rows = (await db.execute(
        select(day.label("d"), SearchResult.sentiment, func.count(SearchResult.id))
        .join(SearchQuery, SearchResult.query_id == SearchQuery.id)
        .where(*qconds).group_by(day, SearchResult.sentiment)
        if qconds else
        select(day.label("d"), SearchResult.sentiment, func.count(SearchResult.id))
        .join(SearchQuery, SearchResult.query_id == SearchQuery.id)
        .group_by(day, SearchResult.sentiment)
    )).all()

    timeline_map: Dict[str, Dict[str, int]] = {}
    for d, cnt in search_day_rows:
        key = d.isoformat() if d else "?"
        timeline_map.setdefault(key, {"searches": 0, "positive": 0, "neutral": 0, "negative": 0})
        timeline_map[key]["searches"] = int(cnt)
    for d, sentiment, cnt in sent_day_rows:
        if not d or sentiment is None:
            continue
        key = d.isoformat()
        bucket = timeline_map.setdefault(key, {"searches": 0, "positive": 0, "neutral": 0, "negative": 0})
        sval = sentiment.value if hasattr(sentiment, "value") else str(sentiment)
        if sval in bucket:
            bucket[sval] = int(cnt)
    timeline = [
        TimelinePoint(date=k, searches=v["searches"], positive=v["positive"], neutral=v["neutral"], negative=v["negative"])
        for k, v in sorted(timeline_map.items())
    ]

    # ── top queries (demand signal) ─────────────────────────────────────────
    top_rows = (await db.execute(
        select(
            SearchQuery.q,
            func.count(SearchQuery.id),
            func.coalesce(func.avg(SearchQuery.total_results), 0),
            func.max(SearchQuery.created_at),
        ).where(*qconds).group_by(SearchQuery.q).order_by(func.count(SearchQuery.id).desc()).limit(15)
        if qconds else
        select(
            SearchQuery.q,
            func.count(SearchQuery.id),
            func.coalesce(func.avg(SearchQuery.total_results), 0),
            func.max(SearchQuery.created_at),
        ).group_by(SearchQuery.q).order_by(func.count(SearchQuery.id).desc()).limit(15)
    )).all()
    top_queries = [
        QueryStat(q=q, count=int(c), avg_results=round(float(avg or 0), 1), last_searched=last)
        for q, c, avg, last in top_rows
    ]

    # ── zero-result queries (coverage blind spots) ──────────────────────────
    zero_rows = (await db.execute(
        select(
            SearchQuery.q,
            func.count(SearchQuery.id),
            func.max(SearchQuery.created_at),
        ).where(*qconds, SearchQuery.total_results == 0).group_by(SearchQuery.q)
        .order_by(func.count(SearchQuery.id).desc()).limit(15)
        if qconds else
        select(
            SearchQuery.q,
            func.count(SearchQuery.id),
            func.max(SearchQuery.created_at),
        ).where(SearchQuery.total_results == 0).group_by(SearchQuery.q)
        .order_by(func.count(SearchQuery.id).desc()).limit(15)
    )).all()
    zero_result_queries = [
        QueryStat(q=q, count=int(c), avg_results=0.0, last_searched=last) for q, c, last in zero_rows
    ]

    # ── result-row breakdowns (sentiment / topic / source / geo / risk) ─────
    async def _slice(column, *, exclude_none=True, exclude_values=()) -> List[Slice]:
        rows = (await db.execute(
            select(column, func.count(SearchResult.id))
            .where(SearchResult.query_id.in_(scoped_ids))
            .group_by(column).order_by(func.count(SearchResult.id).desc())
        )).all()
        out: List[Slice] = []
        for val, cnt in rows:
            if val is None and exclude_none:
                continue
            label = val.value if hasattr(val, "value") else str(val)
            if label in exclude_values:
                continue
            out.append(Slice(label=label, count=int(cnt)))
        return out

    sentiment = await _slice(SearchResult.sentiment)
    topics = await _slice(SearchResult.topic)
    sources = await _slice(SearchResult.source_type)
    geo = await _slice(SearchResult.country)
    risk = await _slice(SearchResult.risk_type, exclude_values=("none",))

    return AnalyticsDashboard(
        scope=role_filter or "all",
        scope_label=scope_label,
        period=period,
        generated_at=datetime.now(timezone.utc),
        kpis=kpis,
        timeline=timeline,
        top_queries=top_queries,
        zero_result_queries=zero_result_queries,
        sentiment=sentiment,
        topics=topics,
        sources=sources,
        geo=geo,
        risk=risk,
    )


@router.get("/role-usage", response_model=List[RoleUsageItem])
async def role_usage(
    period: str = Query("30d", description="7d | 30d | 90d | 180d | 365d | all"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cross-role comparison — how each persona uses search. Admin-only data;
    non-admins receive only their own role's row."""
    start = _period_start(period)
    own = current_user.role.value if isinstance(current_user.role, UserRole) else str(current_user.role)
    base_conds = []
    if start is not None:
        base_conds.append(SearchQuery.created_at >= start)
    if own != ADMIN:
        base_conds.append(SearchQuery.role == own)

    rows = (await db.execute(
        select(
            SearchQuery.role,
            func.count(SearchQuery.id),
            func.count(distinct(func.lower(SearchQuery.q))),
            func.coalesce(func.avg(SearchQuery.total_results), 0),
            func.sum(cast(SearchQuery.total_results == 0, Integer)),
        ).where(*base_conds).group_by(SearchQuery.role)
        if base_conds else
        select(
            SearchQuery.role,
            func.count(SearchQuery.id),
            func.count(distinct(func.lower(SearchQuery.q))),
            func.coalesce(func.avg(SearchQuery.total_results), 0),
            func.sum(cast(SearchQuery.total_results == 0, Integer)),
        ).group_by(SearchQuery.role)
    )).all()

    items: List[RoleUsageItem] = []
    for role_key, total, uniq, avg_res, zero in rows:
        rkey = role_key or "unknown"
        total = int(total or 0)
        zero = int(zero or 0)
        # risk share per role
        rids = select(SearchQuery.id).where(SearchQuery.role == role_key, *base_conds) if base_conds \
            else select(SearchQuery.id).where(SearchQuery.role == role_key)
        tot_r = int((await db.execute(
            select(func.count(SearchResult.id)).where(SearchResult.query_id.in_(rids))
        )).scalar() or 0)
        risk_r = int((await db.execute(
            select(func.count(SearchResult.id)).where(
                SearchResult.query_id.in_(rids),
                SearchResult.risk_type.isnot(None),
                SearchResult.risk_type != "none",
            )
        )).scalar() or 0)
        items.append(RoleUsageItem(
            role=rkey,
            role_label=ROLE_LABELS.get(rkey, rkey),
            total_searches=total,
            unique_queries=int(uniq or 0),
            avg_results=round(float(avg_res or 0), 2),
            zero_result_rate=round(zero / total, 4) if total else 0.0,
            risk_result_share=round(risk_r / tot_r, 4) if tot_r else 0.0,
        ))
    items.sort(key=lambda x: x.total_searches, reverse=True)
    return items


# ════════════════════════════════════════════════════════════════════════════
# REVIEW SENTIMENT ANALYTICS
#
# Aggregates the imported pharmacy product-review corpus (farmaline + medimarket)
# rather than the search-audit log. The review corpus is **shared** across roles
# (everyone analyses the same reviews) — so unlike /dashboard, `role` here selects
# the *metric lens*, not a data filter. Non-admins get their own lens; admins can
# pick any via `?role=`. Sentiment is rating-derived; topic / adverse-event facets
# come from the LLM enrichment pass on the non-positive subset.
# ════════════════════════════════════════════════════════════════════════════

REVIEW_SOURCES = ("farmaline", "medimarket")


class KpiCardModel(BaseModel):
    label: str
    value: str
    sub: Optional[str] = None
    tone: Optional[str] = None  # "ok" | "warn" | "danger"


class ReviewTimelinePoint(BaseModel):
    date: str            # YYYY-MM (monthly bucket)
    reviews: int
    positive: int
    neutral: int
    negative: int


class BrandRow(BaseModel):
    brand: str
    reviews: int
    avg_rating: float
    positive: int
    neutral: int
    negative: int
    sov_percent: float
    momentum: Optional[str] = None  # "up" | "down" | "flat" | null


class ProductRow(BaseModel):
    product: str
    brand: Optional[str]
    reviews: int
    avg_rating: float
    neg_share: float


class TriageItem(BaseModel):
    text: str
    rating: Optional[int]
    brand: Optional[str]
    product: Optional[str]
    language: Optional[str]
    published_at: Optional[datetime]
    is_adverse_event: bool


class LangSentiment(BaseModel):
    language: str
    positive: int
    neutral: int
    negative: int


class ReviewAnalytics(BaseModel):
    scope: str
    scope_label: str
    lens: str                         # role focus description
    period: str
    generated_at: datetime
    sections: List[str]               # ordered block keys the frontend renders for this role
    kpis: List[KpiCardModel]          # role-tailored KPI cards
    sentiment: List[Slice]
    timeline: List[ReviewTimelinePoint]
    sources: List[Slice]
    languages: List[Slice]
    brands: List[BrandRow]
    topics: List[Slice]
    products: List[ProductRow]        # worst-sentiment products (pharmacist)
    triage: List[TriageItem]          # low-rated recent reviews (pharmacist)
    lang_sentiment: List[LangSentiment]
    total_reviews: int
    avg_rating: float
    enriched_reviews: int             # reviews with LLM topic/AE facets
    embedded_reviews: int             # reviews vectorised into Qdrant


# Which blocks each persona sees, in order. Everyone gets the headline KPIs +
# sentiment; the rest is the role lens.
_ROLE_SECTIONS: Dict[str, List[str]] = {
    "pharmacist":    ["sentiment", "triage", "products", "topics", "timeline"],
    "marketing":     ["sentiment", "timeline", "brands", "topics", "lang_sentiment"],
    "brand_manager": ["sentiment", "brands", "timeline", "topics"],
    "admin":         ["sentiment", "timeline", "sources", "brands", "topics", "products", "lang_sentiment"],
}


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


@router.get("/reviews", response_model=ReviewAnalytics)
async def review_analytics(
    role: Optional[str] = Query(None, description="Metric lens (admins only); pharmacist/marketing/brand_manager/admin"),
    period: str = Query("all", description="7d | 30d | 90d | 180d | 365d | all (reviews are historical → 'all' default)"),
    product: Optional[str] = Query(None, description="Scope the whole dashboard to one product (exact, case-insensitive)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role_filter, scope_label = _resolve_scope(current_user, role)
    lens_key = role_filter or ADMIN  # admin "all" view uses the admin lens
    start = _period_start(period)

    base_conds = [Mention.source_type.in_(REVIEW_SOURCES), Mention.is_deleted.is_(False)]
    if start is not None:
        base_conds.append(Mention.published_at >= start)
    if product and product.strip():
        base_conds.append(func.lower(Mention.product_name) == product.strip().lower())

    # ── headline totals ──────────────────────────────────────────────────────
    tot_row = (await db.execute(
        select(func.count(Mention.id), func.coalesce(func.avg(Mention.rating), 0))
        .where(*base_conds)
    )).one()
    total_reviews = int(tot_row[0] or 0)
    avg_rating = round(float(tot_row[1] or 0), 2)

    # ── sentiment split (rating-derived) ──────────────────────────────────────
    sent_rows = (await db.execute(
        select(MentionClassification.sentiment, func.count(Mention.id))
        .join(MentionClassification, MentionClassification.mention_id == Mention.id)
        .where(*base_conds)
        .group_by(MentionClassification.sentiment)
    )).all()
    sent_map = {(s.value if hasattr(s, "value") else str(s)): int(c) for s, c in sent_rows if s is not None}
    pos, neu, neg = sent_map.get("positive", 0), sent_map.get("neutral", 0), sent_map.get("negative", 0)
    sentiment = [Slice(label=k, count=v) for k, v in (("positive", pos), ("neutral", neu), ("negative", neg)) if v]

    # ── monthly timeline ──────────────────────────────────────────────────────
    month = func.to_char(func.date_trunc("month", Mention.published_at), "YYYY-MM")
    tl_rows = (await db.execute(
        select(month.label("m"), MentionClassification.sentiment, func.count(Mention.id))
        .join(MentionClassification, MentionClassification.mention_id == Mention.id)
        .where(*base_conds, Mention.published_at.isnot(None))
        .group_by("m", MentionClassification.sentiment).order_by("m")
    )).all()
    tl: Dict[str, Dict[str, int]] = {}
    for m, s, c in tl_rows:
        if not m:
            continue
        b = tl.setdefault(m, {"reviews": 0, "positive": 0, "neutral": 0, "negative": 0})
        sval = s.value if hasattr(s, "value") else str(s)
        b["reviews"] += int(c)
        if sval in b:
            b[sval] = int(c)
    # keep the last 60 months so the chart stays readable
    timeline = [ReviewTimelinePoint(date=k, **v) for k, v in sorted(tl.items())][-60:]

    # ── source & language splits ──────────────────────────────────────────────
    src_rows = (await db.execute(
        select(Mention.source_type, func.count(Mention.id)).where(*base_conds)
        .group_by(Mention.source_type).order_by(func.count(Mention.id).desc())
    )).all()
    sources = [Slice(label=str(s), count=int(c)) for s, c in src_rows]
    lang_rows = (await db.execute(
        select(Mention.language, func.count(Mention.id)).where(*base_conds)
        .group_by(Mention.language).order_by(func.count(Mention.id).desc())
    )).all()
    languages = [Slice(label=str(l or "?"), count=int(c)) for l, c in lang_rows]

    # ── per-brand performance (avg rating, sentiment split, SoV, momentum) ────
    pos_c = func.sum(case((MentionClassification.sentiment == Sentiment.positive, 1), else_=0))
    neu_c = func.sum(case((MentionClassification.sentiment == Sentiment.neutral, 1), else_=0))
    neg_c = func.sum(case((MentionClassification.sentiment == Sentiment.negative, 1), else_=0))
    brand_rows = (await db.execute(
        select(
            Mention.brand_name,
            func.count(Mention.id),
            func.coalesce(func.avg(Mention.rating), 0),
            pos_c, neu_c, neg_c,
        )
        .join(MentionClassification, MentionClassification.mention_id == Mention.id)
        .where(*base_conds, Mention.brand_name.isnot(None))
        .group_by(Mention.brand_name)
        .order_by(func.count(Mention.id).desc())
        .limit(20)
    )).all()

    # momentum: avg rating in the last 365d vs the prior 365d, per brand
    now = datetime.now(timezone.utc)
    recent_start, prior_start = now - timedelta(days=365), now - timedelta(days=730)
    mom_rows = (await db.execute(
        select(
            Mention.brand_name,
            func.avg(case((Mention.published_at >= recent_start, Mention.rating))),
            func.avg(case((
                (Mention.published_at >= prior_start) & (Mention.published_at < recent_start),
                Mention.rating))),
        )
        .where(*base_conds, Mention.brand_name.isnot(None), Mention.published_at.isnot(None))
        .group_by(Mention.brand_name)
    )).all()
    mom_map: Dict[str, Optional[str]] = {}
    for b, rec, pri in mom_rows:
        if rec is None or pri is None:
            mom_map[b] = None
        else:
            d = float(rec) - float(pri)
            mom_map[b] = "up" if d > 0.15 else "down" if d < -0.15 else "flat"

    brands = [
        BrandRow(
            brand=b or "?", reviews=int(cnt), avg_rating=round(float(ar or 0), 2),
            positive=int(p or 0), neutral=int(n or 0), negative=int(g or 0),
            sov_percent=_pct(int(cnt), total_reviews), momentum=mom_map.get(b),
        )
        for b, cnt, ar, p, n, g in brand_rows
    ]

    # ── topic mix (from LLM enrichment) ───────────────────────────────────────
    topic_rows = (await db.execute(
        select(MentionClassification.topic, func.count(Mention.id))
        .join(MentionClassification, MentionClassification.mention_id == Mention.id)
        .where(*base_conds, MentionClassification.topic.isnot(None))
        .group_by(MentionClassification.topic).order_by(func.count(Mention.id).desc())
    )).all()
    topics = [Slice(label=(t.value if hasattr(t, "value") else str(t)), count=int(c)) for t, c in topic_rows]

    # ── product ratings grid — most-reviewed products (min 3), sorted client-side
    prod_rows = (await db.execute(
        select(
            Mention.product_name, Mention.brand_name,
            func.count(Mention.id), func.coalesce(func.avg(Mention.rating), 0), neg_c,
        )
        .join(MentionClassification, MentionClassification.mention_id == Mention.id)
        .where(*base_conds, Mention.product_name.isnot(None))
        .group_by(Mention.product_name, Mention.brand_name)
        .having(func.count(Mention.id) >= 3)
        .order_by(func.count(Mention.id).desc())
        .limit(150)
    )).all()
    products = [
        ProductRow(product=p, brand=b, reviews=int(cnt), avg_rating=round(float(ar or 0), 2),
                   neg_share=_pct(int(g or 0), int(cnt)))
        for p, b, cnt, ar, g in prod_rows
    ]

    # ── triage queue (pharmacist): recent low-rated / AE-flagged reviews ──────
    triage_rows = (await db.execute(
        select(
            Mention.clean_text, Mention.rating, Mention.brand_name, Mention.product_name,
            Mention.language, Mention.published_at, MentionClassification.is_adverse_event_candidate,
        )
        .join(MentionClassification, MentionClassification.mention_id == Mention.id)
        .where(*base_conds, Mention.rating <= 2)
        .order_by(MentionClassification.is_adverse_event_candidate.desc(),
                  Mention.published_at.desc().nullslast())
        .limit(25)
    )).all()
    triage = [
        TriageItem(text=(t or "")[:300], rating=r, brand=b, product=p, language=lg,
                   published_at=pa, is_adverse_event=bool(ae))
        for t, r, b, p, lg, pa, ae in triage_rows
    ]

    # ── nl-vs-fr sentiment (marketing) ────────────────────────────────────────
    ls_rows = (await db.execute(
        select(Mention.language, MentionClassification.sentiment, func.count(Mention.id))
        .join(MentionClassification, MentionClassification.mention_id == Mention.id)
        .where(*base_conds, Mention.language.isnot(None))
        .group_by(Mention.language, MentionClassification.sentiment)
    )).all()
    ls: Dict[str, Dict[str, int]] = {}
    for lg, s, c in ls_rows:
        b = ls.setdefault(lg, {"positive": 0, "neutral": 0, "negative": 0})
        sval = s.value if hasattr(s, "value") else str(s)
        if sval in b:
            b[sval] = int(c)
    lang_sentiment = sorted(
        [LangSentiment(language=k, **v) for k, v in ls.items()],
        key=lambda x: -(x.positive + x.neutral + x.negative),
    )[:6]

    # ── enrichment / embedding coverage ───────────────────────────────────────
    enriched = int((await db.execute(
        select(func.count(Mention.id))
        .join(MentionClassification, MentionClassification.mention_id == Mention.id)
        .where(*base_conds, MentionClassification.model_name == settings.OPENAI_MODEL)
    )).scalar() or 0)
    embedded = int((await db.execute(
        select(func.count(Mention.id)).where(*base_conds, Mention.qdrant_point_id.isnot(None))
    )).scalar() or 0)

    ae_count = int((await db.execute(
        select(func.count(Mention.id))
        .join(MentionClassification, MentionClassification.mention_id == Mention.id)
        .where(*base_conds, MentionClassification.is_adverse_event_candidate.is_(True))
    )).scalar() or 0)

    # ── role-tailored KPI cards ───────────────────────────────────────────────
    nps = round(_pct(pos, total_reviews) - _pct(neg, total_reviews), 1)
    common = [
        KpiCardModel(label="Reviews", value=f"{total_reviews:,}"),
        KpiCardModel(label="Avg rating", value=f"{avg_rating:.2f}", sub="out of 5"),
    ]
    if lens_key == "pharmacist":
        kpis = common + [
            KpiCardModel(label="Negative", value=f"{_pct(neg, total_reviews)}%",
                         sub=f"{neg:,} reviews", tone="danger" if _pct(neg, total_reviews) > 10 else "warn"),
            KpiCardModel(label="Adverse-event flags", value=f"{ae_count:,}",
                         sub="LLM-detected", tone="danger" if ae_count else None),
            KpiCardModel(label="Low-rated (1–2★)", value=f"{len(triage_rows):,}+", sub="triage queue"),
        ]
    elif lens_key == "marketing":
        kpis = common + [
            KpiCardModel(label="Positive", value=f"{_pct(pos, total_reviews)}%", sub=f"{pos:,} reviews", tone="ok"),
            KpiCardModel(label="Net sentiment (NPS-style)", value=f"{nps:+.0f}",
                         sub="% positive − % negative", tone="ok" if nps > 0 else "warn"),
            KpiCardModel(label="Brands tracked", value=f"{len(brands):,}+"),
        ]
    elif lens_key == "brand_manager":
        top_brand = brands[0].brand if brands else "—"
        kpis = common + [
            KpiCardModel(label="Top brand by volume", value=top_brand,
                         sub=f"{brands[0].sov_percent}% SoV" if brands else None),
            KpiCardModel(label="Positive", value=f"{_pct(pos, total_reviews)}%", tone="ok"),
            KpiCardModel(label="Negative", value=f"{_pct(neg, total_reviews)}%",
                         tone="danger" if _pct(neg, total_reviews) > 10 else None),
        ]
    else:  # admin
        kpis = common + [
            KpiCardModel(label="Positive", value=f"{_pct(pos, total_reviews)}%", tone="ok"),
            KpiCardModel(label="Negative", value=f"{_pct(neg, total_reviews)}%"),
            KpiCardModel(label="LLM-enriched", value=f"{_pct(enriched, total_reviews)}%", sub=f"{enriched:,} reviews"),
            KpiCardModel(label="In Qdrant", value=f"{_pct(embedded, total_reviews)}%", sub=f"{embedded:,} vectors"),
        ]

    return ReviewAnalytics(
        scope=role_filter or "all",
        scope_label=scope_label,
        lens=ROLE_FOCUS.get(lens_key, ""),
        period=period,
        generated_at=now,
        sections=_ROLE_SECTIONS.get(lens_key, _ROLE_SECTIONS["admin"]),
        kpis=kpis,
        sentiment=sentiment,
        timeline=timeline,
        sources=sources,
        languages=languages,
        brands=brands,
        topics=topics,
        products=products,
        triage=triage,
        lang_sentiment=lang_sentiment,
        total_reviews=total_reviews,
        avg_rating=avg_rating,
        enriched_reviews=enriched,
        embedded_reviews=embedded,
    )


class ProductSuggestion(BaseModel):
    product: str
    brand: Optional[str]
    reviews: int
    avg_rating: float


@router.get("/reviews/products", response_model=List[ProductSuggestion])
async def review_product_suggest(
    q: str = Query("", description="Product-name search fragment (case-insensitive, matches anywhere)"),
    limit: int = Query(10, ge=1, le=25),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Typeahead suggestions for the Reviews product search — distinct product names
    matching `q`, ranked by review volume."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    rows = (await db.execute(
        select(
            Mention.product_name,
            func.max(Mention.brand_name),
            func.count(Mention.id),
            func.coalesce(func.avg(Mention.rating), 0),
        )
        .where(
            Mention.source_type.in_(REVIEW_SOURCES),
            Mention.is_deleted.is_(False),
            Mention.product_name.isnot(None),
            Mention.product_name.ilike(f"%{q}%"),
        )
        .group_by(Mention.product_name)
        .order_by(func.count(Mention.id).desc())
        .limit(limit)
    )).all()
    return [
        ProductSuggestion(product=p, brand=b, reviews=int(c), avg_rating=round(float(ar or 0), 2))
        for p, b, c, ar in rows
    ]