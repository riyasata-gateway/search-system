import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_pharmacist, write_audit_log
from core.config import settings
from core.database import get_db
from models.adverse_event import AdverseEventCandidate, AdverseEventReviewStatus
from models.mention import Mention
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


class FlaggedResultIn(BaseModel):
    """One risk-flagged live-search result the user wants escalated."""
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    text: str
    country: Optional[str] = None
    language: Optional[str] = None
    published_at: Optional[datetime] = None
    risk_type: Optional[str] = None
    query: Optional[str] = None


class EscalateFromSearchIn(BaseModel):
    query: Optional[str] = None
    results: List[FlaggedResultIn]


class EscalateResult(BaseModel):
    created: int
    skipped: int
    total: int


@router.get("/", response_model=List[AdverseEventOut])
async def list_adverse_events(
    review_status: Optional[AdverseEventReviewStatus] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    # Pharmacovigilance review is a regulated clinical function → pharmacist + admin only.
    current_user: User = Depends(require_pharmacist),
):
    q = select(AdverseEventCandidate)
    if review_status:
        q = q.where(AdverseEventCandidate.review_status == review_status)
    q = q.order_by(AdverseEventCandidate.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/from-search", response_model=EscalateResult)
async def escalate_from_search(
    request: Request,
    body: EscalateFromSearchIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist risk-flagged *live-search* results into the review queue."""
    created = 0
    skipped = 0
    now = datetime.now(timezone.utc)
    retention = now + timedelta(days=settings.MENTION_RETENTION_DAYS)

    for r in body.results:
        text = (r.text or "").strip()
        if not text:
            skipped += 1
            continue

        # Dedup key: source URL + text — stable across repeated escalations.
        text_hash = hashlib.sha256(f"{r.source_url or ''}|{text}".encode("utf-8")).hexdigest()

        mention = (await db.execute(
            select(Mention).where(Mention.text_hash == text_hash)
        )).scalar_one_or_none()

        if mention is None:
            mention = Mention(
                source_type=r.source_type,
                source_url=r.source_url,
                country=r.country,
                language=r.language,
                published_at=r.published_at,
                collected_at=now,
                text_hash=text_hash,
                raw_text=text,
                clean_text=text,
                query_used=(r.query or body.query),
                retention_expires_at=retention,
            )
            db.add(mention)
            await db.flush()

        existing = (await db.execute(
            select(AdverseEventCandidate).where(AdverseEventCandidate.mention_id == mention.id)
        )).scalar_one_or_none()
        if existing:
            skipped += 1
            continue

        db.add(AdverseEventCandidate(
            mention_id=mention.id,
            description=text[:1000],
            review_status=AdverseEventReviewStatus.pending,
            created_at=now,
        ))
        created += 1

    await write_audit_log(
        db,
        current_user.id,
        "adverse_event_escalate_from_search",
        "adverse_event_candidate",
        None,
        request.client.host if request.client else None,
        detail=f"query={body.query!r}; created={created}; skipped={skipped}",
    )
    await db.commit()
    return EscalateResult(created=created, skipped=skipped, total=len(body.results))


@router.put("/{candidate_id}/review", response_model=AdverseEventOut)
async def review_adverse_event(
    request: Request,
    candidate_id: int,
    body: ReviewUpdate,
    db: AsyncSession = Depends(get_db),
    # Only a qualified pharmacovigilance reviewer (pharmacist/admin) may adjudicate.
    current_user: User = Depends(require_pharmacist),
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
        f"adverse_event_{body.review_status.value}",
        "adverse_event_candidate",
        str(candidate_id),
        request.client.host if request.client else None,
        detail=f"pharmacovigilance_ref={body.pharmacovigilance_ref!r}",
    )
    await db.commit()
    await db.refresh(candidate)
    return candidate
