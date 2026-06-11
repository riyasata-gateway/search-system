"""Per-search metrics — persists the role-tailored DIA metrics computed for each
/search/* call, alongside the search-audit row.

Two tiers (see SEARCH_METRICS_DESIGN.md):
  • snapshot  — descriptive stats of the result batch (always present)
  • framework — corpus-based DIA intelligence (BPI, SoV, momentum, lifecycle,
                launch readiness) for the resolved brand (null when the query
                doesn't resolve to a known brand)

Typed scalar columns hold the headline numbers (queryable/aggregatable across
searches); the full metric bundles + breakdowns live in jsonb.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class SearchMetric(Base):
    __tablename__ = "search_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("search_queries.id", ondelete="CASCADE"),
        unique=True, index=True, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), index=True,
    )
    role: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    mode: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # ── brand resolution ────────────────────────────────────────────────────
    brand_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    brand_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    brand_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # ── framework tier (nullable when unresolved) ───────────────────────────
    bpi: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    bpi_awareness: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    bpi_adoption: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    bpi_sentiment: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    bpi_market_fit: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    bpi_confidence: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    adoption_is_proxy: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    sov_percent: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    momentum_score: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)
    lifecycle_stage: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    launch_readiness: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)

    # ── snapshot tier (always) ───────────────────────────────────────────────
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sentiment_index: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    net_sentiment_label: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    reach_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    engagement_rate: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    risk_share: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    official_coverage: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    source_diversity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── detail bundles ────────────────────────────────────────────────────────
    framework: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    headline: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    query = relationship("SearchQuery")
