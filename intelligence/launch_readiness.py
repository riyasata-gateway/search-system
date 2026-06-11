"""Launch Readiness Score — Phase 2 brand-side composite.

For a brand × country, answers: "How ready is this brand to launch / scale
its campaign now?"

  LaunchReadiness = w1 · BPI
                  + w2 · LifecycleFit
                  + w3 · MomentumGate
                  + w4 · SafetyClearance
                  + w5 · Freshness

Where:
  • BPI                 — already a 0–100 composite. Weighted 0.35.
  • LifecycleFit        — 100 if launch/growth, 60 if pre_launch, 40 if maturity,
                          15 if decline, 0 if unknown. Weighted 0.25.
  • MomentumGate        — momentum_score clamped to 0–100. Weighted 0.20.
  • SafetyClearance     — 100 − (negative_share·100) − (risk_flag_share·100).
                          Penalises brands with active adverse-event signal.
                          Weighted 0.15.
  • Freshness           — 100 if any mention < 14 days old, decaying linearly
                          to 0 at 180 days. Weighted 0.05.

A score ≥ 70 is "go". 40–70 is "monitor". < 40 is "hold".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.logging import get_logger
from intelligence.anomaly import detect_anomaly
from intelligence.brand_potential_index import compute_bpi
from intelligence.lifecycle import LifecycleStage, classify_lifecycle
from intelligence.momentum import compute_momentum
from intelligence.output_schema import MetricBundle, as_score, clamp_score
from models.brand import Brand
from models.mention import Mention, MentionClassification, MentionEntity, RiskType, Sentiment

logger = get_logger(__name__)


LIFECYCLE_FIT = {
    LifecycleStage.launch: 100.0,
    LifecycleStage.growth: 95.0,
    LifecycleStage.pre_launch: 60.0,
    LifecycleStage.maturity: 40.0,
    LifecycleStage.decline: 15.0,
    LifecycleStage.unknown: 0.0,
}

WEIGHTS = {
    "bpi": 0.35,
    "lifecycle": 0.25,
    "momentum": 0.20,
    "safety": 0.15,
    "freshness": 0.05,
}


@dataclass
class LaunchReadinessResult:
    brand_id: int
    brand_name: str
    country: Optional[str]
    score: float
    verdict: str             # "go" | "monitor" | "hold"
    bpi: float
    lifecycle_stage: str
    lifecycle_fit: float
    momentum_score: float
    safety_score: float
    freshness_score: float
    confidence: float
    sample_size: int

    def to_bundle(self) -> MetricBundle:
        return MetricBundle(
            name="launch_readiness",
            metrics=[
                as_score(self.score, "Launch Readiness",
                         confidence=self.confidence,
                         sample_size=self.sample_size),
                as_score(self.bpi, "BPI"),
                as_score(self.lifecycle_fit, f"Lifecycle: {self.lifecycle_stage}"),
                as_score(self.momentum_score, "Momentum"),
                as_score(self.safety_score, "Safety clearance"),
                as_score(self.freshness_score, "Freshness"),
            ],
            context={
                "brand_id": self.brand_id,
                "brand_name": self.brand_name,
                "country": self.country,
                "verdict": self.verdict,
            },
        )


def _safety_score(
    db: Session,
    brand_id: int,
    country: Optional[str],
    window_days: int = 90,
) -> tuple[float, int]:
    """100 minus negative-share and risk-share penalties. Returns (score, sample)."""
    since = date.today() - timedelta(days=window_days)
    rows_q = (
        select(MentionClassification.sentiment, MentionClassification.risk_type)
        .join(MentionEntity, MentionEntity.mention_id == MentionClassification.mention_id)
        .join(Mention, Mention.id == MentionEntity.mention_id)
        .where(
            MentionEntity.entity_type == "brand",
            MentionEntity.entity_id == brand_id,
            Mention.published_at >= since,
            Mention.is_deleted.is_(False),
        )
    )
    if country:
        rows_q = rows_q.where(Mention.country == country)
    rows = db.execute(rows_q).fetchall()
    total = len(rows)
    # Below a minimum base the score isn't meaningful — return neutral (not a
    # confident "95% cleared" off one or two mentions).
    MIN_SAFETY_BASE = 5
    if total < MIN_SAFETY_BASE:
        return 50.0, total
    negative = sum(1 for r in rows if r.sentiment == Sentiment.negative)
    risky = sum(1 for r in rows if r.risk_type and r.risk_type != RiskType.none)
    neg_share = negative / total
    risk_share = risky / total
    # "Safety clearance" = absence of genuine SAFETY signals, not general mood.
    # Risk-flagged mentions (adverse-event/quality/safety) penalise fully; plain
    # negative sentiment is a much weaker safety signal (a grumpy-but-safe review
    # shouldn't read as "unsafe"), so it's down-weighted.
    raw = 100.0 - (risk_share * 100.0) - (neg_share * 40.0)
    return clamp_score(raw), total


def _freshness_score(
    db: Session,
    brand_id: int,
    country: Optional[str],
) -> float:
    """Linear decay: 100 if newest mention is today, 0 at 180+ days old."""
    from core.source_taxonomy import DEMAND_SOURCE_TYPES
    q = (
        select(func.max(Mention.published_at))
        .join(MentionEntity, MentionEntity.mention_id == Mention.id)
        .where(
            MentionEntity.entity_type == "brand",
            MentionEntity.entity_id == brand_id,
            Mention.is_deleted.is_(False),
            # Freshness = recency of CONSUMER activity. A collection-stamped
            # reference row (BCFI/openFDA/etc.) must not make a brand look "fresh".
            Mention.source_type.in_(DEMAND_SOURCE_TYPES),
        )
    )
    if country:
        q = q.where(Mention.country == country)
    newest = db.execute(q).scalar()
    if newest is None:
        return 0.0
    age = max(0, (date.today() - newest.date()).days)
    if age <= 14:
        return 100.0
    if age >= 180:
        return 0.0
    return clamp_score(100.0 - ((age - 14) / (180 - 14)) * 100.0)


def _verdict(score: float) -> str:
    if score >= 70:
        return "go"
    if score >= 40:
        return "monitor"
    return "hold"


def compute_launch_readiness(
    db: Session,
    brand_id: int,
    country: Optional[str] = None,
) -> Optional[LaunchReadinessResult]:
    brand = db.get(Brand, brand_id)
    if brand is None:
        return None

    bpi_result = compute_bpi(db, brand_id, country=country)
    lifecycle = classify_lifecycle(db, "brand", brand_id, country=country)
    momentum = compute_momentum(db, "brand", brand_id, country=country, period="30d")
    safety, safety_n = _safety_score(db, brand_id, country)
    freshness = _freshness_score(db, brand_id, country)

    bpi_score = bpi_result.bpi_score if bpi_result else 0.0
    lifecycle_fit = LIFECYCLE_FIT.get(lifecycle.stage, 0.0)
    momentum_score = momentum.momentum_score

    # Blend the weighted components, but drop momentum when there's no activity to
    # read (its 50 baseline isn't a real signal) and renormalise so it isn't counted
    # as a neutral filler dragging the score toward the middle.
    parts = {
        "bpi": bpi_score,
        "lifecycle": lifecycle_fit,
        "safety": safety,
        "freshness": freshness,
    }
    if momentum.has_signal:
        parts["momentum"] = momentum_score
    weight_total = sum(WEIGHTS[k] for k in parts)
    score = clamp_score(sum(WEIGHTS[k] * v for k, v in parts.items()) / weight_total)

    confidence = (
        (bpi_result.components.confidence if bpi_result else 0.0) * 0.5
        + (lifecycle.confidence * 0.3)
        + min(1.0, safety_n / 20.0) * 0.2
    )

    return LaunchReadinessResult(
        brand_id=brand_id,
        brand_name=brand.name,
        country=country,
        score=round(score, 2),
        verdict=_verdict(score),
        bpi=bpi_score,
        lifecycle_stage=lifecycle.stage.value,
        lifecycle_fit=lifecycle_fit,
        momentum_score=momentum_score,
        safety_score=round(safety, 2),
        freshness_score=round(freshness, 2),
        confidence=round(confidence, 3),
        sample_size=safety_n,
    )


def rank_launch_readiness(
    db: Session,
    country: Optional[str] = None,
    limit: int = 20,
) -> List[LaunchReadinessResult]:
    brand_ids = [int(r[0]) for r in db.execute(select(Brand.id)).fetchall()]
    out: List[LaunchReadinessResult] = []
    for bid in brand_ids:
        r = compute_launch_readiness(db, bid, country=country)
        if r:
            out.append(r)
    out.sort(key=lambda r: r.score, reverse=True)
    logger.info("launch_readiness_ranked", country=country, n=len(out))
    return out[:limit]
