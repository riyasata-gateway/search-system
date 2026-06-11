"""Substitution guidance — what to swap when there's a shortage or competitor pressure.

Triggers from two sources:
  • SHORTAGE: an alert of type `shortage` (or pharmacy inventory.in_stock = false)
  • COMPETITOR_PRESSURE: a brand losing share-of-voice rapidly to a peer

For each trigger, returns ranked substitute products inside the same category,
filtered by what the requesting pharmacy actually stocks. Output is purely
information — no auto-orders, no clinical claims.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.logging import get_logger
from intelligence.flywheel import weight_for
from models.action_event import ActionSubjectType
from models.mention import Mention, MentionEntity
from models.pharmacy import Pharmacy, PharmacyInventory
from models.product import Product, ProductCategory

logger = get_logger(__name__)


@dataclass
class SubstituteCandidate:
    product_id: int
    product_name: str
    category_id: Optional[int]
    in_stock_at_pharmacy: bool
    mention_volume_30d: int
    flywheel_weight: float
    score: float
    reason: str


def _category_peer_products(db: Session, target_product: Product) -> List[Product]:
    if target_product.category_id is None:
        return []
    q = (
        select(Product)
        .where(
            Product.category_id == target_product.category_id,
            Product.id != target_product.id,
        )
    )
    return list(db.execute(q).scalars().all())


def _mention_volume(
    db: Session, product_id: int, country: Optional[str], window_days: int = 30
) -> int:
    since = date.today() - timedelta(days=window_days)
    q = (
        select(func.count(Mention.id))
        .join(MentionEntity, MentionEntity.mention_id == Mention.id)
        .where(
            MentionEntity.entity_type == "product",
            MentionEntity.entity_id == product_id,
            Mention.published_at >= since,
            Mention.is_deleted.is_(False),
        )
    )
    if country:
        q = q.where(Mention.country == country)
    return int(db.execute(q).scalar() or 0)


def suggest_substitutes(
    db: Session,
    target_product_id: int,
    pharmacy_id: Optional[int] = None,
    reason: str = "shortage",
    limit: int = 5,
) -> List[SubstituteCandidate]:
    """Rank substitute candidates inside the same category."""
    target = db.get(Product, target_product_id)
    if target is None or target.category_id is None:
        return []

    category = db.get(ProductCategory, target.category_id)
    pharmacy = db.get(Pharmacy, pharmacy_id) if pharmacy_id else None
    country = pharmacy.country if pharmacy else None

    peers = _category_peer_products(db, target)
    if not peers:
        return []

    stock_lookup: dict[int, bool] = {}
    if pharmacy_id:
        inv_rows = db.execute(
            select(PharmacyInventory.product_id, PharmacyInventory.in_stock).where(
                PharmacyInventory.pharmacy_id == pharmacy_id,
                PharmacyInventory.product_id.in_([p.id for p in peers]),
            )
        ).fetchall()
        stock_lookup = {int(r.product_id): bool(r.in_stock) for r in inv_rows}

    out: List[SubstituteCandidate] = []
    for p in peers:
        vol = _mention_volume(db, p.id, country)
        in_stock = stock_lookup.get(p.id, False)
        weight = weight_for(
            db, ActionSubjectType.recommendation,
            bucket_value=category.slug if category else "",
        )
        # Stocked products rank above non-stocked; within each tier, mention volume wins.
        score = (vol + 1) * weight * (2.0 if in_stock else 1.0)
        out.append(
            SubstituteCandidate(
                product_id=p.id,
                product_name=p.name,
                category_id=p.category_id,
                in_stock_at_pharmacy=in_stock,
                mention_volume_30d=vol,
                flywheel_weight=round(weight, 3),
                score=round(score, 2),
                reason=reason,
            )
        )

    out.sort(key=lambda c: c.score, reverse=True)
    logger.info(
        "substitutes_ranked",
        target_product=target.name,
        pharmacy_id=pharmacy_id,
        count=len(out),
    )
    return out[:limit]
