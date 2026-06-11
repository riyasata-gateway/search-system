from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.logging import get_logger
from models.mention import Mention, MentionEntity
from models.product import competitor_group_products
from models.trend import TrendPeriod, TrendSignal

logger = get_logger(__name__)


@dataclass
class SOVEntry:
    entity_id: int
    entity_type: str
    mention_count: int
    share_percent: float
    sentiment_breakdown: Dict[str, int]


def compute_share_of_voice(
    db: Session,
    competitor_group_id: int,
    country: Optional[str] = None,
    period: TrendPeriod = TrendPeriod.days_30,
) -> List[SOVEntry]:
    """
    Compute share of voice for all products in a competitor group.
    Returns sorted list (highest share first).
    """
    product_ids_result = db.execute(
        select(competitor_group_products.c.product_id).where(
            competitor_group_products.c.competitor_group_id == competitor_group_id
        )
    ).fetchall()
    product_ids = [r[0] for r in product_ids_result]

    if not product_ids:
        return []

    q = (
        select(
            TrendSignal.entity_id,
            func.sum(TrendSignal.mention_count).label("mention_count"),
        )
        .where(
            TrendSignal.entity_type == "product",
            TrendSignal.entity_id.in_(product_ids),
            TrendSignal.period == period,
        )
    )
    if country:
        q = q.where(TrendSignal.country == country)

    q = q.group_by(TrendSignal.entity_id)
    rows = db.execute(q).fetchall()

    total = sum(r.mention_count for r in rows) or 1
    entries = []
    for row in rows:
        from models.mention import MentionClassification, Sentiment
        sent_q = db.execute(
            select(MentionClassification.sentiment, func.count().label("cnt"))
            .join(MentionEntity, MentionEntity.mention_id == MentionClassification.mention_id)
            .where(
                MentionEntity.entity_type == "product",
                MentionEntity.entity_id == row.entity_id,
            )
            .group_by(MentionClassification.sentiment)
        ).fetchall()
        sentiment_breakdown = {str(s.sentiment): s.cnt for s in sent_q if s.sentiment}

        entries.append(SOVEntry(
            entity_id=row.entity_id,
            entity_type="product",
            mention_count=row.mention_count,
            share_percent=round((row.mention_count / total) * 100, 2),
            sentiment_breakdown=sentiment_breakdown,
        ))

    return sorted(entries, key=lambda x: x.share_percent, reverse=True)
