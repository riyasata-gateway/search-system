"""Flywheel closure — feed action telemetry back into the D layer.

Two surfaces:

  • `log_action()` — write a single event (called from API routers when a
    user accepts/dismisses/acts on a recommendation, alert, AI suggestion,
    or any other surfaced action).

  • `acceptance_signals()` — aggregate the action_events table into a
    per-category / per-subject-type acceptance ratio. Downstream consumers
    (the pharmacist recommender, alert engine, momentum scoring) use these
    ratios to up-weight signals that historically resulted in user action,
    completing the DIA loop "each action enriches the data".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from core.logging import get_logger
from models.action_event import ActionDecision, ActionEvent, ActionSubjectType

logger = get_logger(__name__)


# Decisions that count as "positive signal" for boosting future recommendations.
POSITIVE_DECISIONS = {ActionDecision.accepted, ActionDecision.acted_upon}
NEGATIVE_DECISIONS = {ActionDecision.skipped, ActionDecision.dismissed}


@dataclass
class AcceptanceSignal:
    subject_type: str
    bucket_key: str        # category, alert_type, etc. — pulled from context JSON
    total: int
    positive: int
    negative: int
    acceptance_rate: float   # 0–1
    weight_multiplier: float  # what callers should multiply their base score by


def log_action(
    db: Session,
    user_id: Optional[int],
    subject_type: ActionSubjectType,
    subject_id: str,
    decision: ActionDecision,
    context: Optional[Dict[str, Any]] = None,
) -> ActionEvent:
    """Write a single action event. Commits."""
    evt = ActionEvent(
        user_id=user_id,
        subject_type=subject_type,
        subject_id=str(subject_id),
        decision=decision,
        context=context or {},
        created_at=datetime.utcnow(),
    )
    db.add(evt)
    db.commit()
    db.refresh(evt)
    logger.info(
        "action_logged",
        user_id=user_id,
        subject_type=subject_type.value,
        subject_id=subject_id,
        decision=decision.value,
    )
    return evt


def acceptance_signals(
    db: Session,
    subject_type: Optional[ActionSubjectType] = None,
    bucket_key: str = "category",
    window_days: int = 90,
) -> List[AcceptanceSignal]:
    """Aggregate acceptance per bucket extracted from the context JSON.

    `bucket_key` names a JSONB key in `context` we'll group by — e.g.
    "category" if recommendations stash {"category": "allergy"} in context.
    """
    since = datetime.utcnow() - timedelta(days=window_days)
    bucket_expr = ActionEvent.context[bucket_key].astext.label("bucket")

    positive_decisions = [d.value for d in POSITIVE_DECISIONS]
    negative_decisions = [d.value for d in NEGATIVE_DECISIONS]

    q = (
        select(
            ActionEvent.subject_type,
            bucket_expr,
            func.count(ActionEvent.id).label("total"),
            func.sum(
                case((ActionEvent.decision.in_(positive_decisions), 1), else_=0)
            ).label("positive"),
            func.sum(
                case((ActionEvent.decision.in_(negative_decisions), 1), else_=0)
            ).label("negative"),
        )
        .where(ActionEvent.created_at >= since)
        .group_by(ActionEvent.subject_type, bucket_expr)
    )
    if subject_type:
        q = q.where(ActionEvent.subject_type == subject_type)

    out: List[AcceptanceSignal] = []
    for row in db.execute(q).fetchall():
        if not row.bucket:
            continue
        total = int(row.total)
        positive = int(row.positive or 0)
        negative = int(row.negative or 0)
        if total < 3:  # too small to draw conclusions from
            continue
        rate = positive / total
        # Smoothed multiplier: bayes-prior of 0.5 with 5 phantom observations.
        smoothed = (positive + 0.5 * 5) / (total + 5)
        multiplier = 0.5 + smoothed  # range ~0.5 (always rejected) to ~1.5 (always accepted)
        out.append(
            AcceptanceSignal(
                subject_type=row.subject_type.value if hasattr(row.subject_type, "value") else str(row.subject_type),
                bucket_key=row.bucket,
                total=total,
                positive=positive,
                negative=negative,
                acceptance_rate=round(rate, 3),
                weight_multiplier=round(multiplier, 3),
            )
        )
    out.sort(key=lambda s: s.acceptance_rate, reverse=True)
    return out


def weight_for(
    db: Session,
    subject_type: ActionSubjectType,
    bucket_value: str,
    bucket_key: str = "category",
    window_days: int = 90,
) -> float:
    """Single-call helper used inside recommender / alert pipelines."""
    signals = acceptance_signals(db, subject_type, bucket_key=bucket_key, window_days=window_days)
    for s in signals:
        if s.bucket_key == bucket_value:
            return s.weight_multiplier
    return 1.0  # no data → neutral weight
