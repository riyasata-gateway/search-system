"""Market data + de-identified prescription event tables.

These hold the commercial data the DIA framework calls "Market Data" (IQVIA
/ GERS / IMS unit sales + revenue) and "EHR / Rx" (de-identified prescription
events). Both are ingested via CSV upload through `api/routers/market_data.py`
because the real-world feeds arrive as periodic file drops, not APIs.

GDPR notes:
  • PrescriptionEvent uses an HMAC-pseudonymised `hcp_id_hash` — never a
    real prescriber identifier.
  • PrescriptionEvent has the same `retention_expires_at` pattern as Mention
    so the existing retention sweep can age it out.
  • MarketData is non-personal aggregate; no retention sweep needed.
"""
import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class MarketDataSource(str, enum.Enum):
    iqvia = "iqvia"
    gers = "gers"
    ims = "ims"
    other = "other"


class MarketDataPeriod(str, enum.Enum):
    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"


class MarketData(Base, TimestampMixin):
    """Per-product unit + revenue aggregate from a commercial market data feed."""
    __tablename__ = "market_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[MarketDataSource] = mapped_column(
        Enum(MarketDataSource), nullable=False, default=MarketDataSource.other
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    brand_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("brands.id", ondelete="SET NULL"), nullable=True
    )
    country: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    region: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    period: Mapped[MarketDataPeriod] = mapped_column(
        Enum(MarketDataPeriod), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    units: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    revenue_eur: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    market_share_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), nullable=True,
        comment="Pre-computed share within the source's competitive set"
    )
    source_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "source", "product_id", "brand_id", "country", "region",
            "period", "period_start",
            name="uq_market_data_row",
        ),
    )


class PrescriptionEvent(Base):
    """A single de-identified prescription event.

    No PII: hcp_id_hash is an HMAC over the original prescriber identifier,
    patient_age_band is a 10-year bucket, and there is no patient identifier.
    """
    __tablename__ = "prescription_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    brand_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("brands.id", ondelete="SET NULL"), nullable=True, index=True
    )
    country: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    region: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    hcp_id_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True,
        comment="HMAC of original prescriber ID — never the real identifier"
    )
    hcp_specialty: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    patient_age_band: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True,
        comment="10-year bucket, e.g. '30-39'"
    )
    patient_sex: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    rx_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    units: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_new_to_brand: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="True when this HCP has not prescribed this brand in the prior 90 days"
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    retention_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Wiped by the retention sweep — same policy as Mention"
    )
    source_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class MarketDataImport(Base):
    """Audit row per CSV upload — supports DPIA traceability."""
    __tablename__ = "market_data_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uploaded_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[MarketDataSource] = mapped_column(
        Enum(MarketDataSource), nullable=False
    )
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="'market_data' or 'prescription_event'"
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    notes: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
