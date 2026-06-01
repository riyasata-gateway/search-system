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
from sqlalchemy import Date, Integer, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from core.database import get_db
from core.role_lens import ADMIN, ROLE_LABELS, VALID_ROLES
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