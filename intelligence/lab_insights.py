from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.logging import get_logger
from models.mention import Mention, MentionClassification, MentionEntity, Sentiment, Topic
from models.trend import TrendPeriod, TrendSignal

logger = get_logger(__name__)


@dataclass
class BrandInsight:
    brand_id: int
    period: str
    total_mentions: int
    trend_score: float
    relative_change: Optional[float]
    sentiment_breakdown: Dict[str, int]
    top_topics: List[Dict]
    top_countries: List[Dict]
    source_breakdown: Dict[str, int]
    risk_mention_count: int
    adverse_event_pending: int
    competitor_share_of_voice: List[Dict] = field(default_factory=list)
    source_refs: List[str] = field(default_factory=list)


def build_brand_insight(
    db: Session,
    brand_id: int,
    country: Optional[str] = None,
    language: Optional[str] = None,
    source_type: Optional[str] = None,
    period: TrendPeriod = TrendPeriod.days_30,
) -> BrandInsight:
    period_days = {TrendPeriod.days_7: 7, TrendPeriod.days_30: 30, TrendPeriod.days_90: 90}
    days = period_days[period]
    period_start = date.today() - timedelta(days=days)

    entity_q = select(MentionEntity.mention_id).where(
        MentionEntity.entity_type == "brand",
        MentionEntity.entity_id == brand_id,
    )
    mention_ids = [r[0] for r in db.execute(entity_q).fetchall()]

    if not mention_ids:
        return BrandInsight(
            brand_id=brand_id,
            period=period.value,
            total_mentions=0,
            trend_score=0.0,
            relative_change=None,
            sentiment_breakdown={},
            top_topics=[],
            top_countries=[],
            source_breakdown={},
            risk_mention_count=0,
            adverse_event_pending=0,
        )

    sentiment_rows = db.execute(
        select(MentionClassification.sentiment, func.count().label("cnt"))
        .where(MentionClassification.mention_id.in_(mention_ids))
        .group_by(MentionClassification.sentiment)
    ).fetchall()
    sentiment_breakdown = {str(r.sentiment): r.cnt for r in sentiment_rows if r.sentiment}

    topic_rows = db.execute(
        select(MentionClassification.topic, func.count().label("cnt"))
        .where(MentionClassification.mention_id.in_(mention_ids))
        .group_by(MentionClassification.topic)
        .order_by(func.count().desc())
        .limit(10)
    ).fetchall()
    total_topics = sum(r.cnt for r in topic_rows) or 1
    top_topics = [
        {"topic": str(r.topic), "count": r.cnt, "percent": round((r.cnt / total_topics) * 100, 2)}
        for r in topic_rows if r.topic
    ]

    country_rows = db.execute(
        select(Mention.country, func.count().label("cnt"))
        .where(Mention.id.in_(mention_ids), Mention.country.isnot(None))
        .group_by(Mention.country)
        .order_by(func.count().desc())
        .limit(10)
    ).fetchall()
    top_countries = [{"country": r.country, "count": r.cnt} for r in country_rows]

    source_rows = db.execute(
        select(Mention.source_type, func.count().label("cnt"))
        .where(Mention.id.in_(mention_ids), Mention.source_type.isnot(None))
        .group_by(Mention.source_type)
    ).fetchall()
    source_breakdown = {r.source_type: r.cnt for r in source_rows}

    from models.mention import RiskType
    risk_count = db.execute(
        select(func.count())
        .where(
            MentionClassification.mention_id.in_(mention_ids),
            MentionClassification.risk_type != RiskType.none,
        )
    ).scalar() or 0

    from models.adverse_event import AdverseEventCandidate, AdverseEventReviewStatus
    ae_pending = db.execute(
        select(func.count()).where(
            AdverseEventCandidate.review_status == AdverseEventReviewStatus.pending
        )
    ).scalar() or 0

    trend_rows = db.execute(
        select(TrendSignal)
        .where(
            TrendSignal.entity_type == "brand",
            TrendSignal.entity_id == brand_id,
            TrendSignal.period == period,
        )
        .order_by(TrendSignal.signal_date.desc())
        .limit(1)
    ).scalars().all()

    trend_score = float(trend_rows[0].score) if trend_rows else 0.0
    relative_change = float(trend_rows[0].relative_change) if trend_rows and trend_rows[0].relative_change else None

    source_refs = db.execute(
        select(Mention.source_url)
        .where(
            Mention.id.in_(mention_ids),
            Mention.source_url.isnot(None),
            Mention.is_deleted == False,
        )
        .limit(10)
    ).scalars().all()

    return BrandInsight(
        brand_id=brand_id,
        period=period.value,
        total_mentions=len(mention_ids),
        trend_score=trend_score,
        relative_change=relative_change,
        sentiment_breakdown=sentiment_breakdown,
        top_topics=top_topics,
        top_countries=top_countries,
        source_breakdown=source_breakdown,
        risk_mention_count=risk_count,
        adverse_event_pending=ae_pending,
        source_refs=list(source_refs),
    )
