from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, write_audit_log
from core.database import get_db
from models.alert import Alert, AlertSeverity, AlertType
from models.user import User

router = APIRouter()


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
    if alert_type:
        q = q.where(Alert.alert_type == alert_type)
    if severity:
        q = q.where(Alert.severity == severity)
    if acknowledged is True:
        q = q.where(Alert.acknowledged_at.isnot(None))
    elif acknowledged is False:
        q = q.where(Alert.acknowledged_at.is_(None))

    q = q.order_by(Alert.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


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

    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by = current_user.id
    await write_audit_log(
        db, current_user.id, "acknowledge_alert", "alert", str(alert_id), request.client.host
    )
    await db.commit()
    await db.refresh(alert)
    return alert
