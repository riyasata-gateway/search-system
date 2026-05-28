"""Momentum scoring — second-derivative of trend signals.

`trend_engine.py` already computes mention_count and relative_change (1st
derivative). Momentum adds the missing acceleration term so we can detect
*signals that are speeding up* — the basis for the "weak signal before
competitor" capability called out in the TDAH framework.

Formula (per entity × country × period):

  current_period  = mentions in last N days
  prev_period_1   = mentions in N-to-2N days ago
  prev_period_2   = mentions in 2N-to-3N days ago

  velocity        = (current - prev_1) / max(prev_1, 1)
  prev_velocity   = (prev_1 - prev_2) / max(prev_2, 1)
  acceleration    = velocity - prev_velocity

A positive acceleration means the trend is *accelerating*, not just rising.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.logging import get_logger
from intelligence.output_schema import MetricBundle, as_percent, as_score, clamp_score
from models.mention import Mention, MentionEntity

logger = get_logger(__name__)

PERIOD_TO_DAYS = {"7d": 7, "30d": 30, "90d": 90}


@dataclass
class MomentumResult:
    entity_type: str
    entity_id: int
    country: Optional[str]
    period: str
    current_count: int
    prev_count: int
    prev_prev_count: int
    velocity_pct: float
    prev_velocity_pct: float
    acceleration: float
    momentum_score: float

    def to_bundle(self) -> MetricBundle:
        return MetricBundle(
            name="momentum",
            metrics=[
                as_score(self.momentum_score, "Momentum",
                         comparison_window=f"vs previous {self.period}",
                         sample_size=self.current_count),
                as_percent(self.velocity_pct, "Velocity",
                           comparison_window=f"vs previous {self.period}"),
                as_percent(self.acceleration, "Acceleration",
                           comparison_window="velocity-of-velocity"),
            ],
            context={
                "entity_type": self.entity_type,
                "entity_id": self.entity_id,
                "country": self.country,
                "current_count": self.current_count,
                "prev_count": self.prev_count,
                "prev_prev_count": self.prev_prev_count,
            },
        )


def _count_mentions(
    db: Session,
    entity_type: str,
    entity_id: int,
    start: date,
    end: date,
    country: Optional[str] = None,
) -> int:
    q = (
        select(func.count(Mention.id))
        .join(MentionEntity, MentionEntity.mention_id == Mention.id)
        .where(
            MentionEntity.entity_type == entity_type,
            MentionEntity.entity_id == entity_id,
            Mention.published_at >= start,
            Mention.published_at < end,
            Mention.is_deleted.is_(False),
        )
    )
    if country:
        q = q.where(Mention.country == country)
    return int(db.execute(q).scalar() or 0)


def compute_momentum(
    db: Session,
    entity_type: str,
    entity_id: int,
    country: Optional[str] = None,
    period: str = "30d",
) -> MomentumResult:
    """Compute momentum for one entity over the three rolling windows."""
    days = PERIOD_TO_DAYS.get(period, 30)
    today = date.today()
    cur_start = today - timedelta(days=days)
    prev_start = today - timedelta(days=days * 2)
    prev_prev_start = today - timedelta(days=days * 3)

    cur = _count_mentions(db, entity_type, entity_id, cur_start, today, country)
    prev = _count_mentions(db, entity_type, entity_id, prev_start, cur_start, country)
    prev_prev = _count_mentions(db, entity_type, entity_id, prev_prev_start, prev_start, country)

    velocity = ((cur - prev) / max(prev, 1)) * 100.0
    prev_velocity = ((prev - prev_prev) / max(prev_prev, 1)) * 100.0
    acceleration = velocity - prev_velocity

    # Project acceleration into a 0–100 SCORE. Cap at ±200pp.
    capped = max(-200.0, min(200.0, acceleration))
    momentum_score = clamp_score(50.0 + (capped / 4.0))

    return MomentumResult(
        entity_type=entity_type,
        entity_id=entity_id,
        country=country,
        period=period,
        current_count=cur,
        prev_count=prev,
        prev_prev_count=prev_prev,
        velocity_pct=round(velocity, 2),
        prev_velocity_pct=round(prev_velocity, 2),
        acceleration=round(acceleration, 2),
        momentum_score=round(momentum_score, 2),
    )


def rank_momentum(
    db: Session,
    entity_type: str = "brand",
    country: Optional[str] = None,
    period: str = "30d",
    limit: int = 20,
) -> List[MomentumResult]:
    """Top-N entities by momentum score — used for the 'weak signal' dashboard."""
    days = PERIOD_TO_DAYS.get(period, 30)
    today = date.today()
    cur_start = today - timedelta(days=days)

    candidates_q = (
        select(MentionEntity.entity_id, func.count(Mention.id).label("c"))
        .join(Mention, Mention.id == MentionEntity.mention_id)
        .where(
            MentionEntity.entity_type == entity_type,
            Mention.published_at >= cur_start,
            Mention.is_deleted.is_(False),
        )
        .group_by(MentionEntity.entity_id)
        .order_by(func.count(Mention.id).desc())
        .limit(limit * 3)  # over-fetch — many won't qualify after momentum filter
    )
    if country:
        candidates_q = candidates_q.where(Mention.country == country)

    candidate_ids = [int(r.entity_id) for r in db.execute(candidates_q).fetchall()]
    results = [
        compute_momentum(db, entity_type, eid, country=country, period=period)
        for eid in candidate_ids
    ]
    results.sort(key=lambda r: r.momentum_score, reverse=True)
    logger.info("momentum_ranked", entity_type=entity_type, country=country, n=len(results))
    return results[:limit]
