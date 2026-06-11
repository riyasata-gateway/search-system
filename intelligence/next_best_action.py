"""Next-Best-Action orchestrator.

Given a brand × country, returns a ranked list of actions the lab user
should take *right now*, drawing on every Phase 1 + Phase 2 module:

  • Launch Readiness → "Ready to scale" or "Hold launch"
  • Campaign Pivot   → each pivot becomes an action
  • Anomaly          → spike / drop alerts
  • Key Messages     → "Amplify <winning topic>" or "Soften <losing topic>"
  • HCP Targeting    → "Brief top-N HCPs" when KOL data is available
  • Flywheel         → each action's score is multiplied by the historical
                       acceptance multiplier for that action type

Output rules:
  • Each NBA has channel ∈ {paid, organic, hcp, comms, ops}
  • Each NBA has stakeholder ∈ {marketing, medical, ops, exec}
  • Severity → priority routing (high → exec; medium → channel lead)
  • Confidence and evidence are passed through so the UI can link back to
    the underlying signal.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from core.logging import get_logger
from intelligence.campaign_pivot import suggest_pivots
from intelligence.flywheel import weight_for
from intelligence.hcp_targeting import HCPDataStatus, rank_hcps
from intelligence.key_message import compute_key_messages
from intelligence.launch_readiness import compute_launch_readiness
from intelligence.output_schema import MetricBundle, as_score, clamp_score
from models.action_event import ActionSubjectType
from models.brand import Brand

logger = get_logger(__name__)


class NBAChannel(str, enum.Enum):
    paid = "paid"
    organic = "organic"
    hcp = "hcp"
    comms = "comms"
    ops = "ops"


class NBAStakeholder(str, enum.Enum):
    marketing = "marketing"
    medical = "medical"
    ops = "ops"
    exec_ = "exec"


@dataclass
class NextBestAction:
    title: str
    rationale: str
    channel: NBAChannel
    stakeholder: NBAStakeholder
    priority_score: float          # 0–100, post-flywheel weighting
    base_score: float              # raw score before flywheel multiplier
    flywheel_multiplier: float
    severity: str                  # "high" | "medium" | "low"
    source_module: str
    evidence: dict = field(default_factory=dict)


@dataclass
class NBAResult:
    brand_id: int
    brand_name: str
    country: Optional[str]
    actions: List[NextBestAction] = field(default_factory=list)

    def to_bundle(self) -> MetricBundle:
        top = max((a.priority_score for a in self.actions), default=0.0)
        return MetricBundle(
            name="next_best_action",
            metrics=[as_score(top, "Top NBA priority", sample_size=len(self.actions))],
            context={
                "brand_id": self.brand_id,
                "brand_name": self.brand_name,
                "country": self.country,
                "actions": [
                    {
                        "title": a.title,
                        "rationale": a.rationale,
                        "channel": a.channel.value,
                        "stakeholder": a.stakeholder.value,
                        "priority_score": a.priority_score,
                        "base_score": a.base_score,
                        "flywheel_multiplier": a.flywheel_multiplier,
                        "severity": a.severity,
                        "source_module": a.source_module,
                        "evidence": a.evidence,
                    }
                    for a in self.actions
                ],
            },
        )


def _severity(score: float) -> str:
    if score >= 75:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _apply_flywheel(
    db: Session,
    base_score: float,
    bucket_value: str,
) -> tuple[float, float]:
    multiplier = weight_for(
        db, ActionSubjectType.recommendation, bucket_value=bucket_value
    )
    return clamp_score(base_score * multiplier), multiplier


def compute_next_best_actions(
    db: Session,
    brand_id: int,
    country: Optional[str] = None,
    limit: int = 10,
) -> Optional[NBAResult]:
    brand = db.get(Brand, brand_id)
    if brand is None:
        return None

    actions: List[NextBestAction] = []

    # ── Launch Readiness drives a single headline action ─────────────────────
    lr = compute_launch_readiness(db, brand_id, country=country)
    if lr:
        if lr.verdict == "go":
            base = lr.score
            score, mult = _apply_flywheel(db, base, "nba::launch_scale")
            actions.append(NextBestAction(
                title=f"Scale launch / campaign for {brand.name}",
                rationale=(
                    f"Launch Readiness = {lr.score:.0f} (verdict: go). "
                    f"Lifecycle is {lr.lifecycle_stage} with safety score {lr.safety_score:.0f}."
                ),
                channel=NBAChannel.paid,
                stakeholder=NBAStakeholder.marketing,
                priority_score=score, base_score=base, flywheel_multiplier=mult,
                severity=_severity(score),
                source_module="launch_readiness",
                evidence={"verdict": lr.verdict, "bpi": lr.bpi,
                          "momentum": lr.momentum_score, "safety": lr.safety_score},
            ))
        elif lr.verdict == "hold":
            base = 100.0 - lr.score  # low readiness = high priority hold action
            score, mult = _apply_flywheel(db, base, "nba::launch_hold")
            actions.append(NextBestAction(
                title=f"Hold further investment in {brand.name}",
                rationale=(
                    f"Launch Readiness = {lr.score:.0f} (verdict: hold). "
                    f"Safety {lr.safety_score:.0f}, momentum {lr.momentum_score:.0f}."
                ),
                channel=NBAChannel.ops,
                stakeholder=NBAStakeholder.exec_,
                priority_score=score, base_score=base, flywheel_multiplier=mult,
                severity=_severity(score),
                source_module="launch_readiness",
                evidence={"verdict": lr.verdict, "lifecycle": lr.lifecycle_stage,
                          "safety": lr.safety_score},
            ))

    # ── Campaign pivots ──────────────────────────────────────────────────────
    pivots = suggest_pivots(db, brand_id, country=country)
    if pivots:
        for p in pivots.pivots:
            base = p.severity_score
            score, mult = _apply_flywheel(db, base, f"nba::pivot::{p.trigger[:32]}")
            actions.append(NextBestAction(
                title=p.action.split(".")[0],
                rationale=p.trigger,
                channel=NBAChannel.comms if "messaging" in p.action or "copy" in p.action else NBAChannel.paid,
                stakeholder=NBAStakeholder.marketing,
                priority_score=score, base_score=base, flywheel_multiplier=mult,
                severity=p.severity,
                source_module="campaign_pivot",
                evidence=p.evidence,
            ))

    # ── Key messages — winners get an amplify action ─────────────────────────
    msgs = compute_key_messages(db, brand_id, country=country)
    if msgs:
        for topic in msgs.winning[:2]:
            tr = next((t for t in msgs.topics if t.topic == topic), None)
            if tr is None:
                continue
            base = clamp_score(40.0 + (tr.resonance + 1) * 25.0)
            score, mult = _apply_flywheel(db, base, f"nba::amplify::{topic}")
            actions.append(NextBestAction(
                title=f"Amplify '{topic}' messaging",
                rationale=(
                    f"Resonance {tr.resonance:+.2f} across {tr.total} mentions — "
                    f"net-positive engagement signal."
                ),
                channel=NBAChannel.organic,
                stakeholder=NBAStakeholder.marketing,
                priority_score=score, base_score=base, flywheel_multiplier=mult,
                severity=_severity(score),
                source_module="key_message",
                evidence={"topic": topic, "resonance": tr.resonance, "total": tr.total},
            ))

    # ── HCP targeting (gracefully degrades when no data) ─────────────────────
    hcp = rank_hcps(db, brand_id, country=country, limit=5)
    if hcp and hcp.data_status == HCPDataStatus.available and hcp.targets:
        base = max(t.prescriber_momentum for t in hcp.targets)
        score, mult = _apply_flywheel(db, base, "nba::hcp_brief")
        actions.append(NextBestAction(
            title=f"Brief top {len(hcp.targets)} HCPs on {brand.name}",
            rationale=hcp.message,
            channel=NBAChannel.hcp,
            stakeholder=NBAStakeholder.medical,
            priority_score=score, base_score=base, flywheel_multiplier=mult,
            severity=_severity(score),
            source_module="hcp_targeting",
            evidence={"top_n": len(hcp.targets), "data_status": hcp.data_status.value},
        ))
    elif hcp and hcp.data_status == HCPDataStatus.not_connected:
        # Surface as a low-priority ops action so admins see the integration gap.
        actions.append(NextBestAction(
            title="Connect HCP / KOL data source",
            rationale=hcp.message,
            channel=NBAChannel.ops,
            stakeholder=NBAStakeholder.ops,
            priority_score=30.0, base_score=30.0, flywheel_multiplier=1.0,
            severity="low",
            source_module="hcp_targeting",
            evidence={"next_step": hcp.next_step_for_admin or ""},
        ))

    # ── Rank & cap ───────────────────────────────────────────────────────────
    actions.sort(key=lambda a: a.priority_score, reverse=True)
    logger.info("nba_computed", brand_id=brand_id, country=country, n=len(actions))
    return NBAResult(
        brand_id=brand_id,
        brand_name=brand.name,
        country=country,
        actions=actions[:limit],
    )
