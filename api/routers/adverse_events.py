from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, write_audit_log
from core.database import get_db
from models.adverse_event import AdverseEventCandidate, AdverseEventReviewStatus
from models.user import User

router = APIRouter()


class AdverseEventOut(BaseModel):
    id: int
    mention_id: str
    product_id: Optional[int]
    description: Optional[str]
    review_status: AdverseEventReviewStatus
    reviewed_by: Optional[int]
    reviewed_at: Optional[datetime]
    pharmacovigilance_ref: Optional[str]
    notification_sent_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class ReviewUpdate(BaseModel):
    review_status: AdverseEventReviewStatus
    pharmacovigilance_ref: Optional[str] = None


@router.get("/", response_model=List[AdverseEventOut])
async def list_adverse_events(
    review_status: Optional[AdverseEventReviewStatus] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(AdverseEventCandidate)
    if review_status:
        q = q.where(AdverseEventCandidate.review_status == review_status)
    q = q.order_by(AdverseEventCandidate.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.put("/{candidate_id}/review", response_model=AdverseEventOut)
async def review_adverse_event(
    request: Request,
    candidate_id: int,
    body: ReviewUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Human reviewer updates the status. System NEVER makes the final call —
    per pharma control: adverse event decisions require human review.
    """
    result = await db.execute(
        select(AdverseEventCandidate).where(AdverseEventCandidate.id == candidate_id)
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    candidate.review_status = body.review_status
    candidate.reviewed_by = current_user.id
    candidate.reviewed_at = datetime.now(timezone.utc)
    if body.pharmacovigilance_ref:
        candidate.pharmacovigilance_ref = body.pharmacovigilance_ref

    await write_audit_log(
        db,
        current_user.id,
        f"adverse_event_{body.review_status}",
        "adverse_event_candidate",
        str(candidate_id),
        request.client.host,
        metadata={"pharmacovigilance_ref": body.pharmacovigilance_ref},
    )
    await db.commit()
    await db.refresh(candidate)
    return candidate
