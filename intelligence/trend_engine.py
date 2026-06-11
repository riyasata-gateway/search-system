from datetime import date, timedelta
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import settings
from core.logging import get_logger
from models.mention import Mention, MentionEntity
from models.trend import TrendPeriod, TrendSignal

logger = get_logger(__name__)

PERIOD_DAYS = {
    TrendPeriod.days_7: 7,
    TrendPeriod.days_30: 30,
    TrendPeriod.days_90: 90,
}


def compute_trend_signals(db: Session, period: TrendPeriod = TrendPeriod.days_30) -> int:
    """
    Compute and upsert trend signals per entity, country, city, and source.
    Uses engagement-weighted scoring: mentions with higher engagement_count
    contribute proportionally more to the signal score.
    Computes relative_change vs the previous equivalent period.
    """
    days = PERIOD_DAYS[period]
    today = date.today()
    period_start = today - timedelta(days=days)
    prev_period_start = today - timedelta(days=days * 2)

    entity_q = (
        db.execute(
            select(
                MentionEntity.entity_type,
                MentionEntity.entity_id,
                Mention.country,
                Mention.source_type,
                func.count(Mention.id).label("mention_count"),
                func.coalesce(func.sum(Mention.engagement_count), 0).label("engagement_sum"),
            )
            .join(Mention, Mention.id == MentionEntity.mention_id)
            .where(
                Mention.published_at >= period_start,
                Mention.published_at <= today,
                Mention.is_deleted == False,
            )
            .group_by(
                MentionEntity.entity_type,
                MentionEntity.entity_id,
                Mention.country,
                Mention.source_type,
            )
        )
        .fetchall()
    )

    saved = 0
    for row in entity_q:
        engagement_weighted = float(row.mention_count) + (float(row.engagement_sum) * 0.01)
        score = round(engagement_weighted, 4)

        prev_q = (
            db.execute(
                select(func.count(Mention.id))
                .join(MentionEntity, MentionEntity.mention_id == Mention.id)
                .where(
                    MentionEntity.entity_type == row.entity_type,
                    MentionEntity.entity_id == row.entity_id,
                    Mention.country == row.country,
                    Mention.source_type == row.source_type,
                    Mention.published_at >= prev_period_start,
                    Mention.published_at < period_start,
                    Mention.is_deleted == False,
                )
            )
            .scalar()
        ) or 0

        relative_change = None
        if prev_q > 0:
            relative_change = round(((row.mention_count - prev_q) / prev_q) * 100, 2)

        existing = db.execute(
            select(TrendSignal).where(
                TrendSignal.entity_type == row.entity_type,
                TrendSignal.entity_id == row.entity_id,
                TrendSignal.country == row.country,
                TrendSignal.source_type == row.source_type,
                TrendSignal.signal_date == today,
                TrendSignal.period == period,
            )
        ).scalar_one_or_none()

        if existing:
            existing.score = score
            existing.mention_count = row.mention_count
            existing.relative_change = relative_change
            existing.engagement_count_weighted = engagement_weighted
        else:
            signal = TrendSignal(
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                country=row.country,
                source_type=row.source_type,
                signal_date=today,
                score=score,
                relative_change=relative_change,
                engagement_count_weighted=engagement_weighted,
                period=period,
                mention_count=row.mention_count,
            )
            db.add(signal)
        saved += 1

    db.commit()
    logger.info("trend_signals_computed", period=period.value, signals=saved)
    return saved
