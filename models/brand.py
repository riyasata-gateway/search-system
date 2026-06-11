from typing import List, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


class BrandGroup(Base, TimestampMixin):
    """
    Groups brands that belong to the same laboratory/manufacturer.
    Required because brand_group_id FK in Brand table needs a parent table.
    """
    __tablename__ = "brand_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    brands: Mapped[List["Brand"]] = relationship("Brand", back_populates="brand_group")


class Brand(Base, TimestampMixin):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    country: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String(2)), nullable=True)
    is_competitor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    brand_group_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("brand_groups.id", ondelete="SET NULL"), nullable=True
    )

    # ── Datatopia Brand→Source→KPI framework metadata ────────────────────────
    # Populated by scripts/seed_brand_catalog.py from core/framework_catalog.py.
    # `manufacturer` doubles as the workbook's "Owner".
    category: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # ── Belgian supplier taxonomy (5-code primary category) ──────────────────
    # A coarser, MECE classification axis (NUT/RX/PAC/PEC/OTC) imported from the
    # supplier-categorisation workbook. Distinct from `category` above, which is
    # the fine-grained *competitive family* (e.g. "Dermocosmetics") used for
    # peer-set / share-of-voice math — overwriting that would collapse all peers.
    # Powers the Brand Catalog browse/filter. See core.framework_catalog.PRIMARY_CATEGORIES.
    primary_category: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True, index=True,
        comment="Primary supplier category code: NUT|RX|PAC|PEC|OTC",
    )
    category_confidence: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, comment="Classification confidence: High|Medium"
    )
    category_rationale: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Why this primary_category was assigned"
    )
    tier_a_signal: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Public-web (Tier A) signals available for this brand"
    )
    tier_bc_signal: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Official (Tier B) + proprietary (Tier C) signals"
    )
    kpi_roles: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(String(32)), nullable=True,
        comment="Roles whose primary KPI interest includes this brand"
    )

    brand_group: Mapped[Optional["BrandGroup"]] = relationship("BrandGroup", back_populates="brands")
    products: Mapped[List["Product"]] = relationship("Product", back_populates="brand")
