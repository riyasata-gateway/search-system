from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from core.database import get_db
from models.trend import TrendPeriod, TrendSignal
from models.user import User

router = APIRouter()


class TrendOut(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    country: Optional[str]
    region: Optional[str]
    city: Optional[str]
    language: Optional[str]
    source_type: Optional[str]
    signal_date: date
    score: float
    relative_change: Optional[float]
    engagement_count_weighted: Optional[float]
    period: TrendPeriod
    mention_count: int

    class Config:
        from_attributes = True


class ShareOfVoiceItem(BaseModel):
    entity_type: str
    entity_id: int
    mention_count: int
    share_percent: float
    period: TrendPeriod


@router.get("/", response_model=List[TrendOut])
async def list_trends(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    country: Optional[str] = None,
    region: Optional[str] = None,
    city: Optional[str] = None,
    period: TrendPeriod = TrendPeriod.days_30,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    source_type: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(TrendSignal).where(TrendSignal.period == period)

    if entity_type:
        q = q.where(TrendSignal.entity_type == entity_type)
    if entity_id is not None:
        q = q.where(TrendSignal.entity_id == entity_id)
    if country:
        q = q.where(TrendSignal.country == country)
    if region:
        q = q.where(TrendSignal.region == region)
    if city:
        q = q.where(TrendSignal.city == city)
    if source_type:
        q = q.where(TrendSignal.source_type == source_type)
    if date_from:
        q = q.where(TrendSignal.signal_date >= date_from)
    if date_to:
        q = q.where(TrendSignal.signal_date <= date_to)

    q = q.order_by(TrendSignal.signal_date.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/share-of-voice", response_model=List[ShareOfVoiceItem])
async def share_of_voice(
    competitor_group_id: int,
    country: Optional[str] = None,
    period: TrendPeriod = TrendPeriod.days_30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from models.product import competitor_group_products

    product_ids_q = select(competitor_group_products.c.product_id).where(
        competitor_group_products.c.competitor_group_id == competitor_group_id
    )
    product_ids_result = await db.execute(product_ids_q)
    product_ids = [r[0] for r in product_ids_result.fetchall()]

    if not product_ids:
        return []

    q = (
        select(
            TrendSignal.entity_type,
            TrendSignal.entity_id,
            func.sum(TrendSignal.mention_count).label("mention_count"),
        )
        .where(
            TrendSignal.entity_type == "product",
            TrendSignal.entity_id.in_(product_ids),
            TrendSignal.period == period,
        )
    )
    if country:
        q = q.where(TrendSignal.country == country)

    q = q.group_by(TrendSignal.entity_type, TrendSignal.entity_id)
    result = await db.execute(q)
    rows = result.fetchall()

    total = sum(r.mention_count for r in rows) or 1
    return [
        ShareOfVoiceItem(
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            mention_count=r.mention_count,
            share_percent=round((r.mention_count / total) * 100, 2),
            period=period,
        )
        for r in rows
    ]
