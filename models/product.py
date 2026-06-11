import enum
from typing import List, Optional

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Table, Column
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


class AliasType(str, enum.Enum):
    brand = "brand"
    generic = "generic"
    misspelling = "misspelling"
    local_name = "local_name"
    ingredient = "ingredient"
    category_term = "category_term"


competitor_group_products = Table(
    "competitor_group_products",
    Base.metadata,
    Column("competitor_group_id", Integer, ForeignKey("competitor_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("product_id", Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
)


class ProductCategory(Base, TimestampMixin):
    """
    Proper category entity — supports country-specific names.
    Replaces the VARCHAR category fields that were scattered across the schema.
    """
    __tablename__ = "product_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(128), nullable=False)
    name_fr: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    name_nl: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    name_de: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_otc: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    products: Mapped[List["Product"]] = relationship("Product", back_populates="category")


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("brands.id", ondelete="SET NULL"), nullable=True
    )
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("product_categories.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    active_ingredient: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cnk: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    ean: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_otc: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_prescription: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    country: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String(2)), nullable=True)

    brand: Mapped[Optional["Brand"]] = relationship("Brand", back_populates="products")
    category: Mapped[Optional["ProductCategory"]] = relationship("ProductCategory", back_populates="products")
    aliases: Mapped[List["ProductAlias"]] = relationship("ProductAlias", back_populates="product", cascade="all, delete-orphan")
    competitor_groups: Mapped[List["CompetitorGroup"]] = relationship(
        "CompetitorGroup", secondary=competitor_group_products, back_populates="products"
    )


class ProductAlias(Base):
    """
    Country-specific and language-specific aliases, synonyms, and misspellings.
    Critical for EU multi-country product name handling.
    """
    __tablename__ = "product_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    language: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    alias_type: Mapped[Optional[AliasType]] = mapped_column(Enum(AliasType), nullable=True)

    product: Mapped["Product"] = relationship("Product", back_populates="aliases")


class CompetitorGroup(Base, TimestampMixin):
    """
    Groups competing products for share-of-voice comparison.
    Uses proper many-to-many instead of ARRAY(INTEGER).
    """
    __tablename__ = "competitor_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("product_categories.id", ondelete="SET NULL"), nullable=True
    )

    products: Mapped[List["Product"]] = relationship(
        "Product", secondary=competitor_group_products, back_populates="competitor_groups"
    )
