"""Anomaly detection on trend signals.

Statistical (z-score) outlier detection over a rolling baseline. Outputs a
SCORE 0–100 where ≥ 70 flags an anomaly worthy of operator attention. This
is the lightweight version called out as "Anomaly Detection — ML-free
statistical baseline" in the DIA roadmap; the heavier ML version (Prophet /
isolation forests) can swap in behind the same interface later.

For each entity × country × period:

  daily counts over the last `baseline_days`
  mean μ, stddev σ
  today's value z = (today - μ) / σ
  anomaly_score = sigmoid(z) * 100 normalised so |z| ≥ 3 ⇒ score ≥ 80
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.event_bus import Channel, publish_event
from core.logging import get_logger
from intelligence.output_schema import MetricBundle, as_abs, as_score, clamp_score
from models.mention import Mention, MentionEntity

logger = get_logger(__name__)

# Minimum non-zero days in the baseline before a z-score is trustworthy — an
# explicit min-observations gate replacing the old magic `std < 0.5` cutoff.
_MIN_ACTIVE_DAYS = 3


@dataclass
class AnomalyResult:
    entity_type: str
    entity_id: int
    country: Optional[str]
    today_count: int
    baseline_mean: float
    baseline_stddev: float
    z_score: float
    anomaly_score: float
    is_anomaly: bool
    direction: str  # "spike" | "drop" | "normal"

    def to_bundle(self) -> MetricBundle:
        return MetricBundle(
            name="anomaly",
            metrics=[
                as_score(self.anomaly_score, "Anomaly score"),
                as_abs(self.today_count, "Today's mentions", unit="mentions"),
                as_abs(round(self.baseline_mean, 2), "Baseline mean", unit="mentions/day"),
            ],
            context={
                "entity_type": self.entity_type,
                "entity_id": self.entity_id,
                "country": self.country,
                "z_score": round(self.z_score, 3),
                "stddev": round(self.baseline_stddev, 3),
                "direction": self.direction,
                "is_anomaly": self.is_anomaly,
            },
        )


def _daily_counts(
    db: Session,
    entity_type: str,
    entity_id: int,
    start: date,
    end: date,
    country: Optional[str] = None,
) -> List[int]:
    """Return one count per day in [start, end], zero-filling missing days."""
    from core.source_taxonomy import DEMAND_SOURCE_TYPES
    day_col = func.date(Mention.published_at).label("d")
    q = (
        select(day_col, func.count(Mention.id).label("c"))
        .join(MentionEntity, MentionEntity.mention_id == Mention.id)
        .where(
            MentionEntity.entity_type == entity_type,
            MentionEntity.entity_id == entity_id,
            Mention.published_at >= start,
            Mention.published_at < end,
            Mention.is_deleted.is_(False),
            # Anomaly detection reads CONSUMER activity only — a literature/
            # reference ingest must not register as a demand spike/drop.
            Mention.source_type.in_(DEMAND_SOURCE_TYPES),
        )
        .group_by(day_col)
    )
    if country:
        q = q.where(Mention.country == country)
    rows = db.execute(q).fetchall()
    by_day = {row.d: int(row.c) for row in rows}
    out: List[int] = []
    cursor = start
    while cursor < end:
        out.append(by_day.get(cursor, 0))
        cursor = cursor + timedelta(days=1)
    return out


def _mean_std(values: List[int]) -> tuple[float, float]:
    """Mean + SAMPLE standard deviation (÷ n-1). Population variance (÷ n) biased
    σ low on a short daily series, inflating z-scores."""
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, math.sqrt(var)


def detect_anomaly(
    db: Session,
    entity_type: str,
    entity_id: int,
    country: Optional[str] = None,
    baseline_days: int = 30,
    z_threshold: float = 2.0,
) -> AnomalyResult:
    """Compare today's count vs a rolling baseline. Returns an AnomalyResult."""
    today = date.today()
    baseline_start = today - timedelta(days=baseline_days)
    baseline_end = today  # exclusive — we compute today separately

    baseline_series = _daily_counts(
        db, entity_type, entity_id, baseline_start, baseline_end, country
    )
    today_count = _daily_counts(
        db, entity_type, entity_id, today, today + timedelta(days=1), country
    )[0] if True else 0

    mean, std = _mean_std(baseline_series)
    # A trustworthy z needs a real baseline DISTRIBUTION: non-zero spread AND
    # enough active days. The old magic `std < 0.5` cutoff both masked real
    # low-volume signal and let a single historical spike enable false positives.
    active_days = sum(1 for v in baseline_series if v > 0)
    if std <= 0.0 or active_days < _MIN_ACTIVE_DAYS:
        z = 0.0
    else:
        z = (today_count - mean) / std

    # Map |z| into a 0–100 SCORE. Sigmoid centred at z=2 so threshold ≈ 50.
    score_raw = 100.0 / (1.0 + math.exp(-(abs(z) - 2.0)))
    anomaly_score = clamp_score(score_raw)
    is_anomaly = abs(z) >= z_threshold
    direction = "spike" if z > 0 else ("drop" if z < 0 else "normal")
    if not is_anomaly:
        direction = "normal"

    return AnomalyResult(
        entity_type=entity_type,
        entity_id=entity_id,
        country=country,
        today_count=today_count,
        baseline_mean=mean,
        baseline_stddev=std,
        z_score=z,
        anomaly_score=round(anomaly_score, 2),
        is_anomaly=is_anomaly,
        direction=direction,
    )


def scan_anomalies(
    db: Session,
    entity_type: str = "brand",
    country: Optional[str] = None,
    baseline_days: int = 30,
    z_threshold: float = 2.0,
    limit: int = 50,
) -> List[AnomalyResult]:
    """Sweep all entities of a type and return anomalous ones, sorted by score."""
    today = date.today()
    recent_start = today - timedelta(days=baseline_days)

    candidates_q = (
        select(MentionEntity.entity_id, func.count(Mention.id).label("c"))
        .join(Mention, Mention.id == MentionEntity.mention_id)
        .where(
            MentionEntity.entity_type == entity_type,
            Mention.published_at >= recent_start,
            Mention.is_deleted.is_(False),
        )
        .group_by(MentionEntity.entity_id)
        .having(func.count(Mention.id) >= 5)  # need enough signal to detect anomaly
    )
    if country:
        candidates_q = candidates_q.where(Mention.country == country)
    candidate_ids = [int(r.entity_id) for r in db.execute(candidates_q).fetchall()]

    out: List[AnomalyResult] = []
    for eid in candidate_ids:
        res = detect_anomaly(
            db, entity_type, eid, country=country,
            baseline_days=baseline_days, z_threshold=z_threshold,
        )
        if res.is_anomaly:
            out.append(res)

    out.sort(key=lambda r: r.anomaly_score, reverse=True)
    logger.info("anomalies_scanned", entity_type=entity_type, country=country,
                anomalies=len(out), candidates=len(candidate_ids))

    # Push only HIGH-confidence anomalies onto the bus so SSE subscribers
    # don't drown in low-signal pings.
    for r in out[: min(5, len(out))]:
        if r.anomaly_score >= 80:
            publish_event(Channel.SIGNALS, {
                "event": "signal.anomaly",
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "country": r.country,
                "direction": r.direction,
                "score": r.anomaly_score,
                "z_score": round(r.z_score, 3),
                "today_count": r.today_count,
            })

    return out[:limit]
