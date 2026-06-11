"""B7 — saved-rule alert evaluation.

A user saves a threshold rule ("BPI < 40", "complaint_rate > 10") scoped to a
brand (or, when brand_id is null, to the framework brands). `evaluate_rules_for_owner`
resolves each rule's metric from the live KPI engines, checks the condition, and
creates an in-app `threshold_rule` Alert on breach (deduped within a window).
Delivery to Slack/Teams/email is B8 (deferred); this is in-app only.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.alert import Alert, AlertRule, AlertType, RuleMetric, RuleOperator
from models.brand import Brand

_OPS = {
    RuleOperator.lt: lambda a, b: a < b,
    RuleOperator.lte: lambda a, b: a <= b,
    RuleOperator.gt: lambda a, b: a > b,
    RuleOperator.gte: lambda a, b: a >= b,
}
_OP_SYM = {RuleOperator.lt: "<", RuleOperator.lte: "≤", RuleOperator.gt: ">", RuleOperator.gte: "≥"}

_REVIEW_KEYS = {
    RuleMetric.sentiment: "ph_patient_sentiment",
    RuleMetric.complaint_rate: "ph_complaint_rate",
    RuleMetric.brand_trust: "ph_brand_trust",
    RuleMetric.review_volume: "ph_demand_signal",
}


def metric_value(db: Session, brand: Brand, metric: RuleMetric) -> Optional[float]:
    """Resolve a rule metric to a number from the live engines. None when the
    metric is insufficient/unavailable for the brand (→ rule simply doesn't fire)."""
    if metric == RuleMetric.bpi:
        from intelligence.brand_potential_index import compute_bpi
        r = compute_bpi(db, brand.id)
        return None if (not r or r.insufficient) else float(r.bpi_score)
    if metric == RuleMetric.launch_readiness:
        from intelligence.launch_readiness import compute_launch_readiness
        r = compute_launch_readiness(db, brand.id)
        return float(r.score) if r else None
    if metric == RuleMetric.momentum:
        from intelligence.momentum import compute_momentum
        r = compute_momentum(db, "brand", brand.id)
        return float(r.momentum_score) if (r and r.has_signal) else None
    # review-derived metrics via the framework KPI grid
    from intelligence.framework_kpis import compute_live_values
    v = compute_live_values(db, brand).get(_REVIEW_KEYS[metric]) or {}
    if metric == RuleMetric.review_volume:
        return float(v.get("count") or v.get("value") or 0)
    return None if v.get("value") is None else float(v["value"])


def _scope_brands(db: Session, rule: AlertRule, framework_brand_ids: List[int]) -> List[Brand]:
    if rule.brand_id:
        b = db.get(Brand, rule.brand_id)
        return [b] if b else []
    if not framework_brand_ids:
        return []
    return db.execute(select(Brand).where(Brand.id.in_(framework_brand_ids))).scalars().all()


def evaluate_rule(db: Session, rule: AlertRule, framework_brand_ids: List[int],
                  *, dedupe_window_h: int = 24) -> List[Alert]:
    """Evaluate one rule across its scope; return the Alerts created (not committed)."""
    created: List[Alert] = []
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=dedupe_window_h)
    for brand in _scope_brands(db, rule, framework_brand_ids):
        val = metric_value(db, brand, rule.metric)
        if val is None or not _OPS[rule.operator](val, rule.threshold):
            continue
        # Dedupe: don't re-raise the same rule+brand within the window.
        recent = db.execute(
            select(Alert).where(
                Alert.alert_type == AlertType.threshold_rule,
                Alert.entity_type == "brand", Alert.entity_id == brand.id,
                Alert.created_at >= since,
            )
        ).scalars().all()
        if any((a.payload or {}).get("rule_id") == rule.id for a in recent):
            continue
        desc = (f"{rule.name}: {rule.metric.value} {_OP_SYM[rule.operator]} "
                f"{rule.threshold:g} for {brand.name} (now {round(val, 1)})")
        created.append(Alert(
            alert_type=AlertType.threshold_rule, severity=rule.severity,
            entity_type="brand", entity_id=brand.id, description=desc,
            payload={"rule_id": rule.id, "rule_name": rule.name, "metric": rule.metric.value,
                     "operator": rule.operator.value, "threshold": rule.threshold,
                     "value": round(val, 2), "brand_name": brand.name},
            created_at=now,
        ))
        rule.last_triggered_at = now
    rule.last_evaluated_at = now
    return created


def evaluate_rules_for_owner(db: Session, owner_id: int, framework_brand_ids: List[int]) -> int:
    """Evaluate all of an owner's active rules; persist new alerts; return the count."""
    rules = db.execute(
        select(AlertRule).where(AlertRule.owner_id == owner_id, AlertRule.active.is_(True))
    ).scalars().all()
    total = 0
    for rule in rules:
        for alert in evaluate_rule(db, rule, framework_brand_ids):
            db.add(alert)
            total += 1
    db.commit()
    return total
