from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_lab
from core.database import get_db
from intelligence.inn_resolver import is_belgian_medicine
from models.mention import Mention, MentionClassification, Sentiment, Topic, RiskType
from models.trend import TrendPeriod, TrendSignal
from models.user import User, UserRole

router = APIRouter()


def _enum_val(x):
    """Return the clean string value of a (str) Enum member.

    The sentiment/topic columns are `str`-enum backed, so the raw member would
    serialize via `str(enum)` → e.g. "Sentiment.neutral" / "Topic.general",
    which breaks the frontend colour lookups and shows ugly chart labels. We
    want the bare value ("neutral", "general")."""
    return x.value if hasattr(x, "value") else x


async def _framework_brand_ids(db: AsyncSession, role_value: str):
    """Framework brands whose workbook `kpi_roles` include this role.

    These are the Datatopia tracked brands (La Roche-Posay, Eucerin, …) seeded
    with `category` + `kpi_roles`. They are what each role should be able to
    browse on the brand dashboards, independent of manufacturer ownership.
    """
    from models.brand import Brand

    rows = await db.execute(
        select(Brand.id)
        .where(Brand.category.isnot(None))
        .where(Brand.kpi_roles.contains([role_value]))
    )
    return set(rows.scalars().all())


async def _owned_brand_ids(db: AsyncSession, current_user: User):
    """The set of brand ids a user may view, or None meaning 'all brands'.

    Two things make a brand viewable:
      • **Manufacturer ownership** — a lab user linked to a brand_group owns
        every brand made by that group's manufacturer (e.g. a Sanofi user owns
        Doliprane + Enterogermina + Telfast).
      • **Role interest** — the Datatopia framework brands whose `kpi_roles`
        include this user's role, so the workbook's tracked brands show up in the
        dropdown for the right persona even though they sit in other groups.

    The viewable set is the union of the two. Admins are unrestricted (None).
    """
    if current_user.role == UserRole.admin:
        return None

    fw = await _framework_brand_ids(db, current_user.role.value)
    group_id = getattr(current_user, "brand_group_id", None)
    if not group_id:
        return fw or None

    from models.brand import Brand

    mfrs = [
        m for m in (
            await db.execute(
                select(Brand.manufacturer).where(Brand.brand_group_id == group_id).distinct()
            )
        ).scalars().all()
        if m
    ]
    if not mfrs:
        return fw or None
    ids = (
        await db.execute(select(Brand.id).where(Brand.manufacturer.in_(mfrs)))
    ).scalars().all()
    return set(ids) | fw


async def _resolve_brand_id(
    db: AsyncSession, brand_id: Optional[int], current_user: User
) -> int:
    """Resolve which brand a lab view scopes to, enforcing ownership.

    A non-admin may only view brands in their owned portfolio; an out-of-scope
    `?brand_id` is ignored and we fall back to an owned default. When nothing is
    explicitly chosen we pick the in-scope brand with the most mention links, so
    the dashboard always lands on a brand that actually has data.
    """
    from models.mention import MentionEntity, EntityType

    owned = await _owned_brand_ids(db, current_user)

    if brand_id and (owned is None or brand_id in owned):
        return brand_id

    # Default: the most-mentioned brand within the allowed pool.
    most_q = (
        select(MentionEntity.entity_id, func.count().label("cnt"))
        .where(MentionEntity.entity_type == EntityType.brand)
        .group_by(MentionEntity.entity_id)
        .order_by(func.count().desc())
    )
    if owned is not None:
        most_q = most_q.where(MentionEntity.entity_id.in_(owned))
    row = (await db.execute(most_q.limit(1))).first()
    if row:
        return row[0]

    # No mention-linked brand in scope — fall back to any owned brand so the
    # page still renders (honestly empty) rather than 400-ing.
    if owned:
        return sorted(owned)[0]

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="brand_id required — no brand-linked mentions in the corpus yet",
    )


class MyBrandOut(BaseModel):
    id: int
    name: str
    manufacturer: Optional[str]
    category: Optional[str]
    is_competitor: bool
    has_data: bool
    is_medicine: bool = False


@router.get("/my-brands", response_model=List[MyBrandOut])
async def my_brands(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_lab),
):
    """Brands this user may switch between: their owned portfolio (by
    manufacturer) for marketing/brand_manager, or all brands for admin.
    `has_data` flags which brands actually have linked mentions today.
    """
    from models.brand import Brand
    from models.mention import MentionEntity, EntityType

    # Every role can browse every tracked brand. Only the tracked (framework)
    # brands belong in the picker — legacy seed brands (Doliprane, Advil, …) carry
    # no `category` and have no linked data, so they'd just be dead options.
    # (Manufacturer ownership no longer scopes the picker — the role only changes
    # which KPIs are shown, not which brands are selectable.)
    q = select(Brand).where(Brand.category.isnot(None))
    brands = (await db.execute(q.order_by(Brand.name))).scalars().all()

    data_ids = set(
        (
            await db.execute(
                select(MentionEntity.entity_id)
                .where(MentionEntity.entity_type == EntityType.brand)
                .distinct()
            )
        ).scalars().all()
    )
    return [
        MyBrandOut(
            id=b.id,
            name=b.name,
            manufacturer=b.manufacturer,
            category=b.category,
            is_competitor=bool(b.is_competitor),
            has_data=b.id in data_ids,
            is_medicine=is_belgian_medicine(b.name),
        )
        for b in brands
    ]


class BrandOverviewOut(BaseModel):
    brand_id: int
    country: Optional[str]
    period: TrendPeriod
    total_mentions: int
    trend_score: float
    relative_change: Optional[float]
    top_topics: List[Dict[str, Any]]
    sentiment_breakdown: Dict[str, int]


class CompetitorComparisonItem(BaseModel):
    entity_id: int
    entity_type: str
    mention_count: int
    share_percent: float
    sentiment_positive: int
    sentiment_negative: int
    sentiment_neutral: int
    source_refs: List[str]


class TopicBreakdownItem(BaseModel):
    topic: str
    count: int
    percent: float


class WeeklySummaryOut(BaseModel):
    brand_id: int
    period_start: date
    period_end: date
    summary: str
    generated_at: datetime


class LabDashboardOut(BaseModel):
    brand_id: int
    country: Optional[str]
    period: TrendPeriod
    total_mentions: int
    sentiment_breakdown: Dict[str, int]
    top_topics: List[TopicBreakdownItem]
    risk_alert_count: int
    adverse_event_pending: int
    source_breakdown: Dict[str, int]


@router.get("/dashboard", response_model=LabDashboardOut)
async def lab_dashboard(
    brand_id: Optional[int] = None,
    country: Optional[str] = None,
    language: Optional[str] = None,
    source_type: Optional[str] = None,
    period: TrendPeriod = TrendPeriod.days_30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_lab),
):
    resolved_brand_id = await _resolve_brand_id(db, brand_id, current_user)

    from models.mention import Mention, MentionEntity, EntityType
    from models.adverse_event import AdverseEventCandidate, AdverseEventReviewStatus

    entity_ids_q = await db.execute(
        select(MentionEntity.mention_id).where(
            MentionEntity.entity_type == EntityType.brand,
            MentionEntity.entity_id == resolved_brand_id,
        )
    )
    mention_ids = [r[0] for r in entity_ids_q.fetchall()]

    sentiment_q = await db.execute(
        select(MentionClassification.sentiment, func.count().label("cnt"))
        .where(MentionClassification.mention_id.in_(mention_ids))
        .group_by(MentionClassification.sentiment)
    )
    sentiment_breakdown = {_enum_val(row.sentiment): row.cnt for row in sentiment_q.fetchall() if row.sentiment}

    topic_q = await db.execute(
        select(MentionClassification.topic, func.count().label("cnt"))
        .where(MentionClassification.mention_id.in_(mention_ids))
        .group_by(MentionClassification.topic)
        .order_by(func.count().desc())
        .limit(10)
    )
    topic_rows = topic_q.fetchall()
    total_topic = sum(r.cnt for r in topic_rows) or 1
    top_topics = [
        TopicBreakdownItem(topic=_enum_val(r.topic), count=r.cnt, percent=round((r.cnt / total_topic) * 100, 2))
        for r in topic_rows
        if r.topic
    ]

    risk_q = await db.execute(
        select(func.count()).where(
            MentionClassification.mention_id.in_(mention_ids),
            MentionClassification.risk_type != RiskType.none,
        )
    )
    risk_count = risk_q.scalar() or 0

    ae_q = await db.execute(
        select(func.count()).where(
            AdverseEventCandidate.review_status == AdverseEventReviewStatus.pending
        )
    )
    ae_pending = ae_q.scalar() or 0

    source_q = await db.execute(
        select(Mention.source_type, func.count().label("cnt"))
        .where(Mention.id.in_(mention_ids), Mention.is_deleted == False)
        .group_by(Mention.source_type)
    )
    source_breakdown = {row.source_type: row.cnt for row in source_q.fetchall() if row.source_type}

    return LabDashboardOut(
        brand_id=resolved_brand_id,
        country=country,
        period=period,
        total_mentions=len(mention_ids),
        sentiment_breakdown=sentiment_breakdown,
        top_topics=top_topics,
        risk_alert_count=risk_count,
        adverse_event_pending=ae_pending,
        source_breakdown=source_breakdown,
    )


@router.get("/brand-overview", response_model=BrandOverviewOut)
async def brand_overview(
    brand_id: Optional[int] = None,
    country: Optional[str] = None,
    language: Optional[str] = None,
    source_type: Optional[str] = None,
    period: TrendPeriod = TrendPeriod.days_30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_lab),
):
    resolved_brand_id = await _resolve_brand_id(db, brand_id, current_user)

    q = select(TrendSignal).where(
        TrendSignal.entity_type == "brand",
        TrendSignal.entity_id == resolved_brand_id,
        TrendSignal.period == period,
    )
    if country:
        q = q.where(TrendSignal.country == country)
    if source_type:
        q = q.where(TrendSignal.source_type == source_type)

    result = await db.execute(q.order_by(TrendSignal.signal_date.desc()))
    signals = result.scalars().all()

    total_mentions = sum(s.mention_count for s in signals)
    avg_score = (sum(float(s.score) for s in signals) / len(signals)) if signals else 0.0
    latest_change = float(signals[0].relative_change) if signals and signals[0].relative_change else None

    return BrandOverviewOut(
        brand_id=resolved_brand_id,
        country=country,
        period=period,
        total_mentions=total_mentions,
        trend_score=avg_score,
        relative_change=latest_change,
        top_topics=[],
        sentiment_breakdown={},
    )


@router.get("/competitor-comparison", response_model=List[CompetitorComparisonItem])
async def competitor_comparison(
    competitor_group_id: int,
    country: Optional[str] = None,
    language: Optional[str] = None,
    source_type: Optional[str] = None,
    period: TrendPeriod = TrendPeriod.days_30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_lab),
):
    from models.product import competitor_group_products
    from models.mention import Mention, MentionEntity, EntityType

    product_ids_q = await db.execute(
        select(competitor_group_products.c.product_id).where(
            competitor_group_products.c.competitor_group_id == competitor_group_id
        )
    )
    product_ids = [r[0] for r in product_ids_q.fetchall()]

    items = []
    for pid in product_ids:
        entity_q = await db.execute(
            select(MentionEntity.mention_id).where(
                MentionEntity.entity_type == EntityType.product,
                MentionEntity.entity_id == pid,
            )
        )
        mention_ids = [r[0] for r in entity_q.fetchall()]

        sent_q = await db.execute(
            select(MentionClassification.sentiment, func.count().label("cnt"))
            .where(MentionClassification.mention_id.in_(mention_ids))
            .group_by(MentionClassification.sentiment)
        )
        sent = {row.sentiment: row.cnt for row in sent_q.fetchall() if row.sentiment}

        src_q = await db.execute(
            select(Mention.source_url).where(
                Mention.id.in_(mention_ids),
                Mention.source_url.isnot(None),
                Mention.is_deleted == False,
            ).limit(5)
        )
        source_refs = [r[0] for r in src_q.fetchall() if r[0]]

        items.append(
            CompetitorComparisonItem(
                entity_id=pid,
                entity_type="product",
                mention_count=len(mention_ids),
                share_percent=0.0,
                sentiment_positive=sent.get(Sentiment.positive, 0),
                sentiment_negative=sent.get(Sentiment.negative, 0),
                sentiment_neutral=sent.get(Sentiment.neutral, 0),
                source_refs=source_refs,
            )
        )

    total = sum(i.mention_count for i in items) or 1
    for item in items:
        item.share_percent = round((item.mention_count / total) * 100, 2)

    return sorted(items, key=lambda x: x.mention_count, reverse=True)


@router.get("/sentiment-breakdown", response_model=List[TopicBreakdownItem])
async def sentiment_breakdown(
    brand_id: Optional[int] = None,
    country: Optional[str] = None,
    language: Optional[str] = None,
    source_type: Optional[str] = None,
    period: TrendPeriod = TrendPeriod.days_30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_lab),
):
    resolved_brand_id = await _resolve_brand_id(db, brand_id, current_user)

    from models.mention import MentionEntity, EntityType
    entity_q = await db.execute(
        select(MentionEntity.mention_id).where(
            MentionEntity.entity_type == EntityType.brand,
            MentionEntity.entity_id == resolved_brand_id,
        )
    )
    mention_ids = [r[0] for r in entity_q.fetchall()]

    q = await db.execute(
        select(MentionClassification.sentiment, func.count().label("cnt"))
        .where(MentionClassification.mention_id.in_(mention_ids))
        .group_by(MentionClassification.sentiment)
    )
    rows = q.fetchall()
    total = sum(r.cnt for r in rows) or 1
    return [
        TopicBreakdownItem(topic=_enum_val(r.sentiment), count=r.cnt, percent=round((r.cnt / total) * 100, 2))
        for r in rows
        if r.sentiment
    ]


@router.get("/topic-clusters", response_model=List[TopicBreakdownItem])
async def topic_clusters(
    brand_id: Optional[int] = None,
    country: Optional[str] = None,
    language: Optional[str] = None,
    period: TrendPeriod = TrendPeriod.days_30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_lab),
):
    resolved_brand_id = await _resolve_brand_id(db, brand_id, current_user)

    from models.mention import MentionEntity, EntityType
    entity_q = await db.execute(
        select(MentionEntity.mention_id).where(
            MentionEntity.entity_type == EntityType.brand,
            MentionEntity.entity_id == resolved_brand_id,
        )
    )
    mention_ids = [r[0] for r in entity_q.fetchall()]

    q = await db.execute(
        select(MentionClassification.topic, func.count().label("cnt"))
        .where(MentionClassification.mention_id.in_(mention_ids))
        .group_by(MentionClassification.topic)
        .order_by(func.count().desc())
    )
    rows = q.fetchall()
    total = sum(r.cnt for r in rows) or 1
    return [
        TopicBreakdownItem(topic=_enum_val(r.topic), count=r.cnt, percent=round((r.cnt / total) * 100, 2))
        for r in rows
        if r.topic
    ]


@router.get("/weekly-summary", response_model=WeeklySummaryOut)
async def weekly_summary(
    brand_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_lab),
):
    """LLM-generated executive summary — 'What changed this week?'"""
    resolved_brand_id = await _resolve_brand_id(db, brand_id, current_user)

    from intelligence.llm_summariser import generate_weekly_summary
    from datetime import date, timedelta

    today = date.today()
    # 30-day rolling window vs the prior 30 days — enough span for real
    # period-over-period deltas ("what changed"), unlike a 7-day slice.
    period_start = today - timedelta(days=30)

    summary_text = await generate_weekly_summary(
        brand_id=resolved_brand_id, period_start=period_start, period_end=today, db=db,
        role=getattr(current_user, "role", "brand_manager"),
    )
    return WeeklySummaryOut(
        brand_id=resolved_brand_id,
        period_start=period_start,
        period_end=today,
        summary=summary_text,
        generated_at=datetime.utcnow(),
    )
