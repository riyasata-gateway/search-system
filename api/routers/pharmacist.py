from datetime import datetime
from io import BytesIO
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_pharmacist, write_audit_log
from core.database import get_db
from models.recommendation import Recommendation, RecommendationAction, RecommendationStatus, RecommendationType
from models.trend import TrendSignal, TrendPeriod
from models.user import User

router = APIRouter()


class RecommendationOut(BaseModel):
    id: int
    product_id: Optional[int]
    category_id: Optional[int]
    recommendation_type: RecommendationType
    reason: Optional[str]
    external_trend_score: Optional[float]
    internal_sales_score: Optional[float]
    inventory_gap_score: Optional[float]
    confidence_score: Optional[float]
    action: RecommendationAction
    status: RecommendationStatus
    source_refs: Optional[list]
    created_at: datetime

    class Config:
        from_attributes = True


class ActionUpdate(BaseModel):
    status: RecommendationStatus


class TrendingCategoryOut(BaseModel):
    entity_type: str
    entity_id: int
    country: Optional[str]
    region: Optional[str]
    city: Optional[str]
    score: float
    relative_change: Optional[float]
    mention_count: int


class PharmacistDashboardOut(BaseModel):
    pharmacy_id: int
    pharmacy_name: str
    country: str
    pending_recommendations: int
    trending_categories: List[TrendingCategoryOut]
    top_recommendations: List[RecommendationOut]


@router.get("/dashboard", response_model=PharmacistDashboardOut)
async def pharmacist_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_pharmacist),
):
    if current_user.pharmacy_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not linked to a pharmacy",
        )

    from models.pharmacy import Pharmacy
    pharmacy_result = await db.execute(
        select(Pharmacy).where(Pharmacy.id == current_user.pharmacy_id)
    )
    pharmacy = pharmacy_result.scalar_one_or_none()
    if not pharmacy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pharmacy not found")

    rec_result = await db.execute(
        select(Recommendation).where(
            Recommendation.pharmacy_id == current_user.pharmacy_id,
            Recommendation.status == RecommendationStatus.pending,
        ).order_by(Recommendation.confidence_score.desc()).limit(10)
    )
    recommendations = rec_result.scalars().all()

    trend_result = await db.execute(
        select(TrendSignal).where(
            TrendSignal.entity_type == "category",
            TrendSignal.country == pharmacy.country,
            TrendSignal.period == TrendPeriod.days_30,
        ).order_by(TrendSignal.score.desc()).limit(10)
    )
    trending = trend_result.scalars().all()

    pending_count_result = await db.execute(
        select(Recommendation).where(
            Recommendation.pharmacy_id == current_user.pharmacy_id,
            Recommendation.status == RecommendationStatus.pending,
        )
    )
    pending_count = len(pending_count_result.scalars().all())

    return PharmacistDashboardOut(
        pharmacy_id=pharmacy.id,
        pharmacy_name=pharmacy.name,
        country=pharmacy.country,
        pending_recommendations=pending_count,
        trending_categories=[
            TrendingCategoryOut(
                entity_type=t.entity_type,
                entity_id=t.entity_id,
                country=t.country,
                region=t.region,
                city=t.city,
                score=float(t.score),
                relative_change=float(t.relative_change) if t.relative_change else None,
                mention_count=t.mention_count,
            )
            for t in trending
        ],
        top_recommendations=recommendations,
    )


@router.get("/recommendations", response_model=List[RecommendationOut])
async def list_recommendations(
    recommendation_type: Optional[RecommendationType] = None,
    rec_status: Optional[RecommendationStatus] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_pharmacist),
):
    if current_user.pharmacy_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not linked to a pharmacy")

    q = select(Recommendation).where(Recommendation.pharmacy_id == current_user.pharmacy_id)
    if recommendation_type:
        q = q.where(Recommendation.recommendation_type == recommendation_type)
    if rec_status:
        q = q.where(Recommendation.status == rec_status)

    q = q.order_by(Recommendation.confidence_score.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.put("/recommendations/{rec_id}/action", response_model=RecommendationOut)
async def update_recommendation_action(
    request: Request,
    rec_id: int,
    body: ActionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_pharmacist),
):
    result = await db.execute(
        select(Recommendation).where(
            Recommendation.id == rec_id,
            Recommendation.pharmacy_id == current_user.pharmacy_id,
        )
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")

    rec.status = body.status
    await write_audit_log(
        db, current_user.id, f"recommendation_{body.status}", "recommendation", str(rec_id), request.client.host
    )
    await db.commit()
    await db.refresh(rec)
    return rec


@router.get("/trending-categories", response_model=List[TrendingCategoryOut])
async def trending_categories(
    country: Optional[str] = None,
    region: Optional[str] = None,
    city: Optional[str] = None,
    period: TrendPeriod = TrendPeriod.days_30,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_pharmacist),
):
    q = select(TrendSignal).where(
        TrendSignal.entity_type == "category",
        TrendSignal.period == period,
    )
    if country:
        q = q.where(TrendSignal.country == country)
    if region:
        q = q.where(TrendSignal.region == region)
    if city:
        q = q.where(TrendSignal.city == city)

    q = q.order_by(TrendSignal.score.desc()).limit(limit)
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        TrendingCategoryOut(
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            country=r.country,
            region=r.region,
            city=r.city,
            score=float(r.score),
            relative_change=float(r.relative_change) if r.relative_change else None,
            mention_count=r.mention_count,
        )
        for r in rows
    ]


@router.get("/recommendations/export")
async def export_recommendations(
    request: Request,
    fmt: str = Query("csv", regex="^(csv|xlsx)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_pharmacist),
):
    """Export pharmacist recommendations as CSV or XLSX — Phase 4 deliverable."""
    if current_user.pharmacy_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not linked to a pharmacy")

    result = await db.execute(
        select(Recommendation).where(Recommendation.pharmacy_id == current_user.pharmacy_id)
        .order_by(Recommendation.confidence_score.desc())
    )
    recs = result.scalars().all()

    import pandas as pd

    data = [
        {
            "id": r.id,
            "product_id": r.product_id,
            "category_id": r.category_id,
            "type": r.recommendation_type,
            "action": r.action,
            "confidence_score": r.confidence_score,
            "external_trend_score": r.external_trend_score,
            "internal_sales_score": r.internal_sales_score,
            "inventory_gap_score": r.inventory_gap_score,
            "reason": r.reason,
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in recs
    ]
    df = pd.DataFrame(data)

    buf = BytesIO()
    if fmt == "xlsx":
        df.to_excel(buf, index=False)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "recommendations.xlsx"
    else:
        df.to_csv(buf, index=False)
        media_type = "text/csv"
        filename = "recommendations.csv"

    buf.seek(0)
    await write_audit_log(
        db, current_user.id, "export_recommendations", "recommendation", None, request.client.host
    )
    return StreamingResponse(
        buf,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
