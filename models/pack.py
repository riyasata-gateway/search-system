"""Canonical pack/SKU entity, keyed by CNK (the Belgian APB national pack code).

CNK is language-independent and shared across SAM, the retail channels and the
wholesalers, so it is the right canonical key to fuse Belgian pharmacy data
without over-counting. This table is the backbone of the bilingual, pack-aware
entity model:

    brand family (brands) → pack/SKU (packs.cnk) → active substance / ATC

Each pack carries FR + NL labels (alternate language titles), so the same
physical pack listed in French and Dutch — or in SAM vs a retail catalogue —
resolves to ONE row instead of splitting into duplicates.
"""
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Pack(Base):
    __tablename__ = "packs"

    cnk: Mapped[str] = mapped_column(String(16), primary_key=True)
    brand_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("brands.id", ondelete="SET NULL"), nullable=True, index=True)
    brand_name: Mapped[Optional[str]] = mapped_column(String(256), index=True)
    # Bilingual alternate labels — the anti-duplication mechanism.
    name_fr: Mapped[Optional[str]] = mapped_column(String(512))
    name_nl: Mapped[Optional[str]] = mapped_column(String(512))
    active_substance: Mapped[Optional[str]] = mapped_column(String(256))
    atc: Mapped[Optional[str]] = mapped_column(String(16))
    category: Mapped[Optional[str]] = mapped_column(String(160))
    pharma_form: Mapped[Optional[str]] = mapped_column(String(160))
    ean: Mapped[Optional[str]] = mapped_column(String(32))
    kind: Mapped[Optional[str]] = mapped_column(String(24))  # medicine | parapharmacy
    is_prescription: Mapped[Optional[bool]] = mapped_column(Boolean)
    # retail facts (from the pharmacy channel)
    price: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    old_price: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    in_stock: Mapped[Optional[bool]] = mapped_column(Boolean)
    rating: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    rating_count: Mapped[Optional[int]] = mapped_column(Integer)
    product_url: Mapped[Optional[str]] = mapped_column(String(1024))
    # which sources contributed (sam, farmaline, …)
    sources: Mapped[Optional[list]] = mapped_column(JSONB)
