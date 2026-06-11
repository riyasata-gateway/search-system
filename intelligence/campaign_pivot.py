"""Campaign Pivot recommendations — signal-triggered.

Inputs (composed, all already implemented):
  • Anomaly        (`intelligence/anomaly.detect_anomaly`)
  • Momentum       (`intelligence/momentum.compute_momentum`)
  • Key Messages   (`intelligence/key_message.compute_key_messages`)
  • Flywheel       (`intelligence/flywheel.weight_for`) — acceptance-rate prior

A pivot is suggested when ≥ 1 of these conditions hits with a high
severity. Each suggestion includes:

  • trigger      — the human-readable reason
  • action       — what to do (e.g. "reduce side-effect copy", "amplify
                    efficacy testimonials", "pause paid promotion")
  • severity     — "high" | "medium" | "low"
  • severity_score — 0–100 SCORE used to rank suggestions

The output is intentionally not auto-executable: this is decision support,
not autopilot. The frontend renders the pivot card, the lab user accepts /
dismisses, and the flywheel module logs that decision back.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from core.logging import get_logger
from intelligence.anomaly import detect_anomaly
from intelligence.flywheel import weight_for
from intelligence.key_message import compute_key_messages
from intelligence.momentum import compute_momentum
from intelligence.output_schema import MetricBundle, as_score, clamp_score
from models.action_event import ActionSubjectType
from models.brand import Brand

logger = get_logger(__name__)


@dataclass
class CampaignPivot:
    trigger: str
    action: str
    severity: str
    severity_score: float
    evidence: dict = field(default_factory=dict)


@dataclass
class CampaignPivotResult:
    brand_id: int
    brand_name: str
    country: Optional[str]
    pivots: List[CampaignPivot] = field(default_factory=list)
    flywheel_weight: float = 1.0

    def to_bundle(self) -> MetricBundle:
        # Headline: highest-severity pivot's score. 0 if none.
        top = max((p.severity_score for p in self.pivots), default=0.0)
        return MetricBundle(
            name="campaign_pivot",
            metrics=[as_score(top, "Pivot urgency")],
            context={
                "brand_id": self.brand_id,
                "brand_name": self.brand_name,
                "country": self.country,
                "flywheel_weight": self.flywheel_weight,
                "pivots": [
                    {
                        "trigger": p.trigger,
                        "action": p.action,
                        "severity": p.severity,
                        "severity_score": p.severity_score,
                        "evidence": p.evidence,
                    }
                    for p in self.pivots
                ],
            },
        )


def _severity_from_score(score: float) -> str:
    if score >= 75:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def suggest_pivots(
    db: Session,
    brand_id: int,
    country: Optional[str] = None,
) -> Optional[CampaignPivotResult]:
    brand = db.get(Brand, brand_id)
    if brand is None:
        return None

    pivots: List[CampaignPivot] = []

    # ── Trigger 1: anomalous drop ────────────────────────────────────────────
    anomaly = detect_anomaly(db, "brand", brand_id, country=country)
    if anomaly.is_anomaly and anomaly.direction == "drop":
        pivots.append(CampaignPivot(
            trigger="Sustained drop vs baseline",
            action="Pause paid amplification; refresh creative before re-igniting.",
            severity=_severity_from_score(anomaly.anomaly_score),
            severity_score=anomaly.anomaly_score,
            evidence={"z_score": round(anomaly.z_score, 2),
                      "baseline_mean": round(anomaly.baseline_mean, 2),
                      "today_count": anomaly.today_count},
        ))

    # ── Trigger 2: anomalous spike (could be backlash or breakout) ───────────
    if anomaly.is_anomaly and anomaly.direction == "spike":
        pivots.append(CampaignPivot(
            trigger="Sudden mention spike",
            action="Verify sentiment immediately — amplify if positive, prepare crisis response if negative.",
            severity=_severity_from_score(anomaly.anomaly_score),
            severity_score=anomaly.anomaly_score,
            evidence={"z_score": round(anomaly.z_score, 2),
                      "today_count": anomaly.today_count},
        ))

    # ── Trigger 3: momentum reversal ─────────────────────────────────────────
    momentum = compute_momentum(db, "brand", brand_id, country=country, period="30d")
    if momentum.acceleration <= -50 and momentum.velocity_pct < 0:
        # Decelerating and shrinking — losing the trend
        score = clamp_score(50.0 - momentum.acceleration / 4.0)
        pivots.append(CampaignPivot(
            trigger="Momentum decelerating and turning negative",
            action="Pivot to retention / loyalty messaging; new-acquisition spend has stopped paying back.",
            severity=_severity_from_score(score),
            severity_score=round(score, 2),
            evidence={"velocity_pct": momentum.velocity_pct,
                      "acceleration": momentum.acceleration},
        ))

    # ── Trigger 4: losing topic dominates ────────────────────────────────────
    msgs = compute_key_messages(db, brand_id, country=country)
    if msgs and msgs.losing:
        top_losing = msgs.losing[0]
        # Find the corresponding TopicResonance for evidence
        evidence = next(
            ({"topic": t.topic, "resonance": t.resonance, "negative": t.negative,
              "total": t.total} for t in msgs.topics if t.topic == top_losing),
            {"topic": top_losing},
        )
        score = clamp_score(60.0 + abs(evidence.get("resonance", 0.0)) * 100.0)
        pivots.append(CampaignPivot(
            trigger=f"'{top_losing}' message is generating net-negative reactions",
            action=(
                f"Reduce '{top_losing}' references in active copy; substitute with "
                f"winning topic(s): {', '.join(msgs.winning) if msgs.winning else '— none yet'}."
            ),
            severity=_severity_from_score(score),
            severity_score=round(score, 2),
            evidence=evidence,
        ))

    # ── Trigger 5: no winning message + low resonance overall ────────────────
    if msgs and not msgs.winning and msgs.sample_size >= 10:
        pivots.append(CampaignPivot(
            trigger="No standout positive message across topics",
            action="Test new creative angles — current messaging is not differentiated. Consider LLM-assisted message tuning.",
            severity="medium",
            severity_score=55.0,
            evidence={"sample_size": msgs.sample_size,
                      "underexposed": msgs.underexposed},
        ))

    pivots.sort(key=lambda p: p.severity_score, reverse=True)

    flywheel_w = weight_for(
        db, ActionSubjectType.recommendation,
        bucket_value=f"campaign_pivot::brand::{brand_id}",
    )

    logger.info("campaign_pivots_suggested", brand_id=brand_id,
                country=country, n=len(pivots))
    return CampaignPivotResult(
        brand_id=brand_id,
        brand_name=brand.name,
        country=country,
        pivots=pivots,
        flywheel_weight=flywheel_w,
    )
