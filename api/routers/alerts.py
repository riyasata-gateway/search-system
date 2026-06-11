from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, write_audit_log
from core.database import get_db, get_sync_db
from models.alert import Alert, AlertRule, AlertSeverity, AlertType, RuleMetric, RuleOperator
from models.user import User, UserRole
from sqlalchemy.orm import Session as SyncSession

router = APIRouter()


# Which alert types each role is responsible for. Admin sees everything.
# Pharmacist owns patient-safety & supply; marketing & brand owners share the
# reputation / market-signal types. Keep this in sync with core/role_lens intent.
_ROLE_ALERT_TYPES = {
    # threshold_rule = the user's own saved-rule (B7) breaches — every role sees its own.
    UserRole.pharmacist: {AlertType.adverse_event, AlertType.shortage, AlertType.threshold_rule},
    UserRole.marketing: {
        AlertType.misinformation, AlertType.prescription_promotion,
        AlertType.competitor_spike, AlertType.brand_spike, AlertType.threshold_rule,
    },
    UserRole.brand_manager: {
        AlertType.shortage, AlertType.misinformation, AlertType.prescription_promotion,
        AlertType.competitor_spike, AlertType.brand_spike, AlertType.threshold_rule,
    },
}


def _allowed_alert_types(role) -> Optional[set]:
    """Alert types this role may see, or None for 'all' (admin)."""
    if role == UserRole.admin:
        return None
    return _ROLE_ALERT_TYPES.get(role, set())


# Clean, user-facing descriptions per alert type. We deliberately render these
# (rather than the stored description) so the internal mention UUID never reaches
# the pharmacist, and so collapsed groups read naturally.
_ALERT_DESCRIPTIONS = {
    AlertType.adverse_event: "Adverse event candidate detected — requires human pharmacovigilance review.",
    AlertType.shortage: "Possible product shortage signalled in monitored mentions.",
    AlertType.misinformation: "Possible health misinformation detected in monitored mentions.",
    AlertType.prescription_promotion: "Possible prescription-medicine promotion detected — human review required.",
    AlertType.competitor_spike: "Competitor activity spike detected.",
    AlertType.brand_spike: "Brand mention spike detected.",
}


def _clean_description(alert: Alert) -> str:
    return _ALERT_DESCRIPTIONS.get(alert.alert_type) or (alert.description or "Alert")


class AlertOut(BaseModel):
    id: int
    alert_type: AlertType
    severity: AlertSeverity
    entity_type: Optional[str]
    entity_id: Optional[int]
    description: Optional[str]
    payload: Optional[dict]
    created_at: datetime
    acknowledged_at: Optional[datetime]
    # How many underlying alerts this card represents (duplicates differing only
    # by the underlying mention are collapsed into one).
    count: int = 1

    class Config:
        from_attributes = True


@router.get("/", response_model=List[AlertOut])
async def list_alerts(
    alert_type: Optional[AlertType] = None,
    severity: Optional[AlertSeverity] = None,
    acknowledged: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Alert)
    # Role lens: each persona only sees the alert types relevant to their job.
    allowed = _allowed_alert_types(current_user.role)
    if allowed is not None:
        if not allowed:
            return []
        q = q.where(Alert.alert_type.in_(allowed))
    if alert_type:
        q = q.where(Alert.alert_type == alert_type)
    if severity:
        q = q.where(Alert.severity == severity)
    if acknowledged is True:
        q = q.where(Alert.acknowledged_at.isnot(None))
    elif acknowledged is False:
        q = q.where(Alert.acknowledged_at.is_(None))

    # Fetch a bounded pool newest-first, then collapse near-identical alerts
    # (same type / severity / entity / ack-state) that differ only by the
    # underlying mention. The pharmacist wants one card per real signal.
    q = q.order_by(Alert.created_at.desc()).limit(2000)
    result = await db.execute(q)
    rows = result.scalars().all()

    groups: dict = {}
    order: list = []
    for a in rows:
        key = (a.alert_type, a.severity, a.entity_type, a.entity_id, a.acknowledged_at is not None)
        if key not in groups:
            groups[key] = {"rep": a, "count": 1}
            order.append(key)
        else:
            groups[key]["count"] += 1  # rep stays the newest (rows are desc)

    out: List[AlertOut] = []
    for key in order[skip : skip + limit]:
        rep = groups[key]["rep"]
        item = AlertOut.model_validate(rep)
        item.description = _clean_description(rep)
        item.count = groups[key]["count"]
        out.append(item)
    return out


@router.put("/{alert_id}/acknowledge", response_model=AlertOut)
async def acknowledge_alert(
    request: Request,
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

    now = datetime.now(timezone.utc)
    # Acknowledge the whole collapsed group — every still-open alert sharing this
    # one's type/severity/entity — so the single card the user clicked clears in
    # one action rather than reappearing for each underlying mention.
    siblings = await db.execute(
        select(Alert).where(
            Alert.alert_type == alert.alert_type,
            Alert.severity == alert.severity,
            Alert.acknowledged_at.is_(None),
        )
    )
    acked = 0
    for s in siblings.scalars().all():
        if s.entity_type == alert.entity_type and s.entity_id == alert.entity_id:
            s.acknowledged_at = now
            s.acknowledged_by = current_user.id
            acked += 1

    await write_audit_log(
        db, current_user.id, "acknowledge_alert", "alert", str(alert_id), request.client.host
    )
    await db.commit()
    await db.refresh(alert)
    out = AlertOut.model_validate(alert)
    out.description = _clean_description(alert)
    out.count = acked
    return out


# ─────────────────────────────────────────────────────────────────────────────
# B7 — user-defined saved alert rules (in-app; Slack/Teams/email delivery = B8).
# Sync endpoints (the rule metrics reuse the sync intelligence engines).
# ─────────────────────────────────────────────────────────────────────────────

class AlertRuleIn(BaseModel):
    name: str
    metric: RuleMetric
    operator: RuleOperator
    threshold: float
    brand_id: Optional[int] = None      # null → evaluate across framework brands
    severity: AlertSeverity = AlertSeverity.medium
    active: bool = True


class AlertRuleOut(BaseModel):
    id: int
    name: str
    metric: RuleMetric
    operator: RuleOperator
    threshold: float
    brand_id: Optional[int]
    severity: AlertSeverity
    active: bool
    created_at: datetime
    last_evaluated_at: Optional[datetime]
    last_triggered_at: Optional[datetime]

    class Config:
        from_attributes = True


def _framework_brand_ids_sync(db: SyncSession) -> List[int]:
    from models.brand import Brand
    return list(db.execute(select(Brand.id).where(Brand.category.isnot(None))).scalars().all())


@router.get("/rules", response_model=List[AlertRuleOut])
def list_rules(db: SyncSession = Depends(get_sync_db), current_user: User = Depends(get_current_user)):
    """The current user's saved alert rules."""
    rows = db.execute(
        select(AlertRule).where(AlertRule.owner_id == current_user.id).order_by(AlertRule.created_at.desc())
    ).scalars().all()
    return [AlertRuleOut.model_validate(r) for r in rows]


@router.post("/rules", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(body: AlertRuleIn, db: SyncSession = Depends(get_sync_db),
                current_user: User = Depends(get_current_user)):
    rule = AlertRule(
        owner_id=current_user.id, name=body.name.strip()[:120], metric=body.metric,
        operator=body.operator, threshold=float(body.threshold), brand_id=body.brand_id,
        severity=body.severity, active=body.active, created_at=datetime.now(timezone.utc),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return AlertRuleOut.model_validate(rule)


@router.put("/rules/{rule_id}", response_model=AlertRuleOut)
def update_rule(rule_id: int, body: AlertRuleIn, db: SyncSession = Depends(get_sync_db),
                current_user: User = Depends(get_current_user)):
    rule = db.get(AlertRule, rule_id)
    if rule is None or rule.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.name = body.name.strip()[:120]
    rule.metric = body.metric
    rule.operator = body.operator
    rule.threshold = float(body.threshold)
    rule.brand_id = body.brand_id
    rule.severity = body.severity
    rule.active = body.active
    db.commit()
    db.refresh(rule)
    return AlertRuleOut.model_validate(rule)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, db: SyncSession = Depends(get_sync_db),
                current_user: User = Depends(get_current_user)):
    rule = db.get(AlertRule, rule_id)
    if rule is None or rule.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()


@router.post("/rules/evaluate")
def evaluate_rules(db: SyncSession = Depends(get_sync_db), current_user: User = Depends(get_current_user)):
    """Evaluate the user's active rules now; create in-app alerts on breach."""
    from intelligence.alert_rules import evaluate_rules_for_owner
    n = evaluate_rules_for_owner(db, current_user.id, _framework_brand_ids_sync(db))
    return {"new_alerts": n}
