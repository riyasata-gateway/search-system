from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_lab
from core.database import get_db
from models.mention import Mention, MentionClassification, Sentiment, Topic, RiskType
from models.trend import TrendPeriod, TrendSignal
from models.user import User

router = APIRouter()


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
    resolved_brand_id = brand_id or getattr(current_user, "brand_id", None)
    if resolved_brand_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="brand_id required — pass ?brand_id=<id> or link user to a brand",
        )

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
    sentiment_breakdown = {row.sentiment: row.cnt for row in sentiment_q.fetchall() if row.sentiment}

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
        TopicBreakdownItem(topic=r.topic, count=r.cnt, percent=round((r.cnt / total_topic) * 100, 2))
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
    resolved_brand_id = brand_id or getattr(current_user, "brand_id", None)
    if not resolved_brand_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="brand_id required")

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
    resolved_brand_id = brand_id or getattr(current_user, "brand_id", None)
    if not resolved_brand_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="brand_id required")

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
        TopicBreakdownItem(topic=str(r.sentiment), count=r.cnt, percent=round((r.cnt / total) * 100, 2))
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
    resolved_brand_id = brand_id or getattr(current_user, "brand_id", None)
    if not resolved_brand_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="brand_id required")

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
        TopicBreakdownItem(topic=str(r.topic), count=r.cnt, percent=round((r.cnt / total) * 100, 2))
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
    resolved_brand_id = brand_id or getattr(current_user, "brand_id", None)
    if not resolved_brand_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="brand_id required")

    from intelligence.llm_summariser import generate_weekly_summary
    from datetime import date, timedelta

    today = date.today()
    week_start = today - timedelta(days=7)

    summary_text = await generate_weekly_summary(
        brand_id=resolved_brand_id, period_start=week_start, period_end=today, db=db
    )
    return WeeklySummaryOut(
        brand_id=resolved_brand_id,
        period_start=week_start,
        period_end=today,
        summary=summary_text,
        generated_at=datetime.utcnow(),
    )
