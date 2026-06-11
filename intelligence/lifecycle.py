"""Lifecycle stage classifier.

Classifies a brand or product into one of five lifecycle stages based on
mention volume, age, growth velocity, and sentiment polarity. The classifier
is deliberately rule-based: pharma teams expect explainable stage transitions,
not opaque ML.

Stages (per the DIA framework):

  pre_launch — buzz exists but no/low purchase intent
  launch     — sharp rise from low base, recent first-mention
  growth     — sustained positive velocity, expanding volume
  maturity   — high volume, near-zero velocity
  decline    — sustained negative velocity

Inputs are derived from existing tables — no schema change required.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.logging import get_logger
from intelligence.momentum import compute_momentum
from intelligence.output_schema import MetricBundle, as_abs, as_score
from models.mention import Mention, MentionClassification, MentionEntity, Sentiment

logger = get_logger(__name__)


class LifecycleStage(str, enum.Enum):
    pre_launch = "pre_launch"
    launch = "launch"
    growth = "growth"
    maturity = "maturity"
    decline = "decline"
    unknown = "unknown"


@dataclass
class LifecycleResult:
    entity_type: str
    entity_id: int
    country: Optional[str]
    stage: LifecycleStage
    total_mentions: int
    velocity_pct: float
    days_since_first_mention: Optional[int]
    positive_share: float
    confidence: float

    def to_bundle(self) -> MetricBundle:
        # Stage maps to a coarse SCORE on the 0–100 lifecycle axis for UI rendering.
        stage_score = {
            LifecycleStage.pre_launch: 15.0,
            LifecycleStage.launch: 35.0,
            LifecycleStage.growth: 60.0,
            LifecycleStage.maturity: 85.0,
            LifecycleStage.decline: 50.0,
            LifecycleStage.unknown: 0.0,
        }[self.stage]
        return MetricBundle(
            name="lifecycle",
            metrics=[
                as_score(stage_score, f"Lifecycle: {self.stage.value}",
                         confidence=self.confidence,
                         sample_size=self.total_mentions),
                as_abs(self.total_mentions, "Total mentions", unit="mentions"),
            ],
            context={
                "entity_type": self.entity_type,
                "entity_id": self.entity_id,
                "country": self.country,
                "stage": self.stage.value,
                "velocity_pct": round(self.velocity_pct, 2),
                "days_since_first_mention": self.days_since_first_mention,
                "positive_share": round(self.positive_share, 3),
            },
        )


def _first_mention_age(
    db: Session,
    entity_type: str,
    entity_id: int,
    country: Optional[str],
) -> Optional[int]:
    q = (
        select(func.min(Mention.published_at))
        .join(MentionEntity, MentionEntity.mention_id == Mention.id)
        .where(
            MentionEntity.entity_type == entity_type,
            MentionEntity.entity_id == entity_id,
            Mention.is_deleted.is_(False),
        )
    )
    if country:
        q = q.where(Mention.country == country)
    first = db.execute(q).scalar()
    if not first:
        return None
    return (date.today() - first.date()).days


def _positive_share(
    db: Session,
    entity_type: str,
    entity_id: int,
    country: Optional[str],
    window_days: int = 90,
) -> float:
    since = date.today() - timedelta(days=window_days)
    q = (
        select(MentionClassification.sentiment, func.count().label("c"))
        .join(MentionEntity, MentionEntity.mention_id == MentionClassification.mention_id)
        .join(Mention, Mention.id == MentionEntity.mention_id)
        .where(
            MentionEntity.entity_type == entity_type,
            MentionEntity.entity_id == entity_id,
            Mention.published_at >= since,
            Mention.is_deleted.is_(False),
        )
        .group_by(MentionClassification.sentiment)
    )
    if country:
        q = q.where(Mention.country == country)
    counts = {row.sentiment: int(row.c) for row in db.execute(q).fetchall()}
    pos = counts.get(Sentiment.positive, 0)
    total = sum(counts.values())
    return pos / total if total else 0.0


def classify_lifecycle(
    db: Session,
    entity_type: str,
    entity_id: int,
    country: Optional[str] = None,
) -> LifecycleResult:
    """Rule-based lifecycle stage assignment."""
    momentum = compute_momentum(db, entity_type, entity_id, country=country, period="30d")
    total = momentum.current_count + momentum.prev_count + momentum.prev_prev_count
    age_days = _first_mention_age(db, entity_type, entity_id, country)
    pos_share = _positive_share(db, entity_type, entity_id, country)

    velocity = momentum.velocity_pct

    if total == 0:
        return LifecycleResult(
            entity_type=entity_type,
            entity_id=entity_id,
            country=country,
            stage=LifecycleStage.unknown,
            total_mentions=0,
            velocity_pct=0.0,
            days_since_first_mention=age_days,
            positive_share=pos_share,
            confidence=0.2,
        )

    # Rules — order matters: earlier rules win
    if age_days is not None and age_days <= 30 and momentum.current_count >= 5 and velocity > 100:
        stage = LifecycleStage.launch
        confidence = 0.75
    elif age_days is not None and age_days <= 60 and momentum.current_count < 5 and pos_share > 0.4:
        stage = LifecycleStage.pre_launch
        confidence = 0.55
    elif velocity > 25 and momentum.current_count >= 5:
        stage = LifecycleStage.growth
        confidence = 0.70
    elif velocity < -25:
        stage = LifecycleStage.decline
        confidence = 0.70
    elif abs(velocity) <= 25 and momentum.current_count >= 10:
        stage = LifecycleStage.maturity
        confidence = 0.65
    else:
        stage = LifecycleStage.unknown
        confidence = 0.30

    return LifecycleResult(
        entity_type=entity_type,
        entity_id=entity_id,
        country=country,
        stage=stage,
        total_mentions=total,
        velocity_pct=velocity,
        days_since_first_mention=age_days,
        positive_share=pos_share,
        confidence=confidence,
    )
