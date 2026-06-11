from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from core.database import get_db
from models.mention import Mention, MentionClassification, ReviewStatus, Sentiment, Topic, RiskType
from models.user import User

router = APIRouter()


class MentionOut(BaseModel):
    id: str
    source_type: Optional[str]
    source_url: Optional[str]
    country: Optional[str]
    language: Optional[str]
    published_at: Optional[datetime]
    collected_at: datetime
    clean_text: Optional[str]
    engagement_count: Optional[int]
    query_used: Optional[str]

    class Config:
        from_attributes = True


class MentionSearchOut(BaseModel):
    id: str
    source_type: Optional[str]
    source_url: Optional[str]
    country: Optional[str]
    language: Optional[str]
    published_at: Optional[datetime]
    clean_text: Optional[str]
    engagement_count: Optional[int]
    sentiment: Optional[str]
    topic: Optional[str]
    risk_type: Optional[str]
    is_risk: bool

    class Config:
        from_attributes = True


@router.get("/", response_model=List[MentionOut])
async def list_mentions(
    q: Optional[str] = Query(None, description="Free-text search in mention content"),
    country: Optional[str] = None,
    language: Optional[str] = None,
    source_type: Optional[str] = None,
    sentiment: Optional[Sentiment] = None,
    topic: Optional[Topic] = None,
    risk_type: Optional[RiskType] = None,
    is_otc_only: Optional[bool] = Query(None, description="Filter mentions linked to OTC products only"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Mention).where(Mention.is_deleted == False)

    if q:
        stmt = stmt.where(
            or_(
                Mention.clean_text.ilike(f"%{q}%"),
                Mention.query_used.ilike(f"%{q}%"),
            )
        )
    if country:
        stmt = stmt.where(Mention.country == country)
    if language:
        stmt = stmt.where(Mention.language == language)
    if source_type:
        stmt = stmt.where(Mention.source_type == source_type)
    if date_from:
        stmt = stmt.where(Mention.published_at >= date_from)
    if date_to:
        stmt = stmt.where(Mention.published_at <= date_to)

    stmt = stmt.order_by(Mention.published_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/search", response_model=List[MentionSearchOut])
async def search_mentions(
    q: str = Query(..., min_length=2, description="Brand, drug, or keyword to search"),
    country: Optional[str] = None,
    language: Optional[str] = None,
    source_type: Optional[str] = None,
    sentiment: Optional[Sentiment] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search mentions by keyword/brand/drug name — returns enriched results with sentiment and risk."""
    stmt = (
        select(
            Mention.id,
            Mention.source_type,
            Mention.source_url,
            Mention.country,
            Mention.language,
            Mention.published_at,
            Mention.clean_text,
            Mention.engagement_count,
            MentionClassification.sentiment,
            MentionClassification.topic,
            MentionClassification.risk_type,
        )
        .outerjoin(MentionClassification, MentionClassification.mention_id == Mention.id)
        .where(
            Mention.is_deleted == False,
            or_(
                Mention.clean_text.ilike(f"%{q}%"),
                Mention.query_used.ilike(f"%{q}%"),
            ),
        )
    )

    if country:
        stmt = stmt.where(Mention.country == country)
    if language:
        stmt = stmt.where(Mention.language == language)
    if source_type:
        stmt = stmt.where(Mention.source_type == source_type)
    if sentiment:
        stmt = stmt.where(MentionClassification.sentiment == sentiment)
    if date_from:
        stmt = stmt.where(Mention.published_at >= date_from)
    if date_to:
        stmt = stmt.where(Mention.published_at <= date_to)

    stmt = stmt.order_by(Mention.published_at.desc()).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).fetchall()

    return [
        MentionSearchOut(
            id=str(row.id),
            source_type=row.source_type,
            source_url=row.source_url,
            country=row.country,
            language=row.language,
            published_at=row.published_at,
            clean_text=row.clean_text,
            engagement_count=row.engagement_count,
            sentiment=str(row.sentiment) if row.sentiment else None,
            topic=str(row.topic) if row.topic else None,
            risk_type=str(row.risk_type) if row.risk_type else None,
            is_risk=bool(row.risk_type and str(row.risk_type) != "none"),
        )
        for row in rows
    ]


@router.get("/{mention_id}", response_model=MentionOut)
async def get_mention(
    mention_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Mention).where(Mention.id == mention_id, Mention.is_deleted == False)
    )
    mention = result.scalar_one_or_none()
    if not mention:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mention not found")
    return mention
