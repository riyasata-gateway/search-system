from datetime import date, datetime, timedelta, timezone
from typing import List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.logging import get_logger
from models.pharmacy import Pharmacy, PharmacyInventory, PharmacySale
from models.product import Product, ProductCategory
from models.recommendation import Recommendation, RecommendationAction, RecommendationStatus, RecommendationType
from models.trend import TrendPeriod, TrendSignal

logger = get_logger(__name__)

CONFIDENCE_WEIGHTS = {
    "external_trend": 0.50,
    "inventory_gap": 0.35,
    "internal_sales": 0.15,
}


def _normalise(value: float, max_val: float) -> float:
    if max_val == 0:
        return 0.0
    return min(round(value / max_val, 4), 1.0)


def generate_recommendations(db: Session, pharmacy_id: int) -> int:
    """
    Pharmacist recommendation engine.
    Combines:
    - External demand signals (trend_signals per country/city)
    - Internal sales velocity (pharmacy_sales last 30 days)
    - Inventory gap (products in trending categories not stocked)

    Scoring formula:
    confidence = (external_trend * 0.50) + (inventory_gap * 0.35) + (sales_velocity * 0.15)
    """
    pharmacy = db.get(Pharmacy, pharmacy_id)
    if not pharmacy:
        return 0

    period_start = date.today() - timedelta(days=30)

    trending_categories = db.execute(
        select(TrendSignal)
        .where(
            TrendSignal.entity_type == "category",
            TrendSignal.country == pharmacy.country,
            TrendSignal.period == TrendPeriod.days_30,
        )
        .order_by(TrendSignal.score.desc())
        .limit(20)
    ).scalars().all()

    if not trending_categories:
        return 0

    max_trend_score = max(float(t.score) for t in trending_categories) or 1.0

    inventory_result = db.execute(
        select(PharmacyInventory.product_id)
        .where(PharmacyInventory.pharmacy_id == pharmacy_id, PharmacyInventory.in_stock == True)
    ).fetchall()
    stocked_product_ids = {r[0] for r in inventory_result}

    sales_result = db.execute(
        select(PharmacySale.product_id, func.sum(PharmacySale.quantity).label("total_qty"))
        .where(
            PharmacySale.pharmacy_id == pharmacy_id,
            PharmacySale.sale_date >= period_start,
        )
        .group_by(PharmacySale.product_id)
    ).fetchall()
    sales_map = {r.product_id: r.total_qty for r in sales_result}
    max_sales = max(sales_map.values()) if sales_map else 1

    saved = 0
    for trend in trending_categories:
        category_id = trend.entity_id
        trend_score_norm = _normalise(float(trend.score), max_trend_score)

        products_in_category = db.execute(
            select(Product).where(Product.category_id == category_id, Product.is_otc == True)
        ).scalars().all()

        missing_products = [p for p in products_in_category if p.id not in stocked_product_ids]
        stocked_trending = [p for p in products_in_category if p.id in stocked_product_ids]

        for product in missing_products:
            inventory_gap_score = 1.0
            sales_score = _normalise(float(sales_map.get(product.id, 0)), max_sales)
            confidence = (
                trend_score_norm * CONFIDENCE_WEIGHTS["external_trend"]
                + inventory_gap_score * CONFIDENCE_WEIGHTS["inventory_gap"]
                + sales_score * CONFIDENCE_WEIGHTS["internal_sales"]
            )

            existing = db.execute(
                select(Recommendation).where(
                    Recommendation.pharmacy_id == pharmacy_id,
                    Recommendation.product_id == product.id,
                    Recommendation.recommendation_type == RecommendationType.stock_missing,
                    Recommendation.status == RecommendationStatus.pending,
                )
            ).scalar_one_or_none()

            if existing:
                existing.confidence_score = round(confidence, 4)
                existing.external_trend_score = round(trend_score_norm, 4)
                existing.inventory_gap_score = 1.0
                existing.internal_sales_score = round(sales_score, 4)
            else:
                db.add(Recommendation(
                    pharmacy_id=pharmacy_id,
                    product_id=product.id,
                    category_id=category_id,
                    recommendation_type=RecommendationType.stock_missing,
                    action=RecommendationAction.add,
                    reason=(
                        f"Category '{category_id}' is trending in {pharmacy.country} "
                        f"(trend score: {float(trend.score):.1f}). "
                        f"Product '{product.name}' is not currently stocked."
                    ),
                    external_trend_score=round(trend_score_norm, 4),
                    internal_sales_score=round(sales_score, 4),
                    inventory_gap_score=1.0,
                    confidence_score=round(confidence, 4),
                    status=RecommendationStatus.pending,
                    source_refs=[trend.source_type] if trend.source_type else [],
                    created_at=datetime.now(timezone.utc),
                ))
                saved += 1

        for product in stocked_trending:
            if float(trend.score) > 5.0 and trend.relative_change and float(trend.relative_change) > 20:
                sales_score = _normalise(float(sales_map.get(product.id, 0)), max_sales)
                existing = db.execute(
                    select(Recommendation).where(
                        Recommendation.pharmacy_id == pharmacy_id,
                        Recommendation.product_id == product.id,
                        Recommendation.recommendation_type == RecommendationType.reorder_trending,
                        Recommendation.status == RecommendationStatus.pending,
                    )
                ).scalar_one_or_none()

                if not existing:
                    confidence = (
                        trend_score_norm * 0.60 + sales_score * 0.40
                    )
                    db.add(Recommendation(
                        pharmacy_id=pharmacy_id,
                        product_id=product.id,
                        category_id=category_id,
                        recommendation_type=RecommendationType.reorder_trending,
                        action=RecommendationAction.reorder,
                        reason=(
                            f"'{product.name}' is stocked and trending +{float(trend.relative_change):.0f}% "
                            f"in {pharmacy.country}. Consider reordering to avoid stockout."
                        ),
                        external_trend_score=round(trend_score_norm, 4),
                        internal_sales_score=round(sales_score, 4),
                        inventory_gap_score=0.0,
                        confidence_score=round(confidence, 4),
                        status=RecommendationStatus.pending,
                        source_refs=[trend.source_type] if trend.source_type else [],
                        created_at=datetime.now(timezone.utc),
                    ))
                    saved += 1

    db.commit()
    logger.info("recommendations_generated", pharmacy_id=pharmacy_id, saved=saved)
    return saved
