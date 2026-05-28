import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class RecommendationType(str, enum.Enum):
    stock_missing = "stock_missing"
    reorder_trending = "reorder_trending"
    watch_category = "watch_category"
    deprioritise = "deprioritise"


class RecommendationAction(str, enum.Enum):
    add = "add"
    monitor = "monitor"
    reorder = "reorder"
    ignore = "ignore"


class RecommendationStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    dismissed = "dismissed"


class Recommendation(Base):
    """
    Pharmacist recommendation engine output.
    category_id FK added (was missing in plan — spec says product_id/category_id).
    source_refs added for evidence-linking per pharma compliance requirement.
    Confidence score breakdown exposed (external_trend_score, internal_sales_score,
    inventory_gap_score) with a computed composite confidence_score.
    """
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pharmacy_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pharmacies.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("product_categories.id", ondelete="SET NULL"), nullable=True,
        comment="Category-level recommendation when no specific product is identified"
    )
    recommendation_type: Mapped[RecommendationType] = mapped_column(
        Enum(RecommendationType), nullable=False
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_trend_score: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 4), nullable=True,
        comment="Normalised 0–1 score from external demand signals (Google Trends, forums)"
    )
    internal_sales_score: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 4), nullable=True,
        comment="Normalised 0–1 score from pharmacy own sales velocity"
    )
    inventory_gap_score: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 4), nullable=True,
        comment="Normalised 0–1 score representing the stocking gap vs demand"
    )
    confidence_score: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 4), nullable=True,
        comment="Composite: (external*0.5) + (inventory_gap*0.35) + (sales*0.15)"
    )
    action: Mapped[RecommendationAction] = mapped_column(
        Enum(RecommendationAction), nullable=False
    )
    status: Mapped[RecommendationStatus] = mapped_column(
        Enum(RecommendationStatus), nullable=False, default=RecommendationStatus.pending
    )
    source_refs: Mapped[Optional[list]] = mapped_column(
        JSONB, nullable=True,
        comment="Evidence-linked source URLs supporting this recommendation per pharma compliance rules"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    pharmacy: Mapped["Pharmacy"] = relationship("Pharmacy")
    product: Mapped[Optional["Product"]] = relationship("Product")
    category: Mapped[Optional["ProductCategory"]] = relationship("ProductCategory")
