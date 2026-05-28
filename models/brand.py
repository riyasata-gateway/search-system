from typing import List, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String
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

    brand_group: Mapped[Optional["BrandGroup"]] = relationship("BrandGroup", back_populates="brands")
    products: Mapped[List["Product"]] = relationship("Product", back_populates="brand")
