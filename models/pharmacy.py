from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


class Pharmacy(Base, TimestampMixin):
    __tablename__ = "pharmacies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    region: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Numeric(9, 6), nullable=True)
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    inventory: Mapped[list["PharmacyInventory"]] = relationship(
        "PharmacyInventory", back_populates="pharmacy", cascade="all, delete-orphan"
    )
    sales: Mapped[list["PharmacySale"]] = relationship(
        "PharmacySale", back_populates="pharmacy", cascade="all, delete-orphan"
    )


class PharmacyInventory(Base):
    __tablename__ = "pharmacy_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pharmacy_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pharmacies.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    stock_qty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    pharmacy: Mapped["Pharmacy"] = relationship("Pharmacy", back_populates="inventory")
    product: Mapped["Product"] = relationship("Product")


class PharmacySale(Base):
    __tablename__ = "pharmacy_sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pharmacy_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pharmacies.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    revenue: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    sale_date: Mapped[date] = mapped_column(Date, nullable=False)

    pharmacy: Mapped["Pharmacy"] = relationship("Pharmacy", back_populates="sales")
    product: Mapped["Product"] = relationship("Product")
