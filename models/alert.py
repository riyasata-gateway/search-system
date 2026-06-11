import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class AlertType(str, enum.Enum):
    adverse_event = "adverse_event"
    shortage = "shortage"
    misinformation = "misinformation"
    competitor_spike = "competitor_spike"
    brand_spike = "brand_spike"
    prescription_promotion = "prescription_promotion"
    threshold_rule = "threshold_rule"   # B7 — user-defined saved-rule breach


class RuleMetric(str, enum.Enum):
    """KPIs a saved alert rule can watch (each maps to a live engine value)."""
    bpi = "bpi"
    launch_readiness = "launch_readiness"
    momentum = "momentum"
    sentiment = "sentiment"            # % positive
    complaint_rate = "complaint_rate"  # % negative
    brand_trust = "brand_trust"
    review_volume = "review_volume"


class RuleOperator(str, enum.Enum):
    lt = "lt"
    lte = "lte"
    gt = "gt"
    gte = "gte"


class AlertSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_type: Mapped[AlertType] = mapped_column(Enum(AlertType), nullable=False, index=True)
    severity: Mapped[AlertSeverity] = mapped_column(
        Enum(AlertSeverity), nullable=False, default=AlertSeverity.medium
    )
    entity_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    acknowledger: Mapped[Optional["User"]] = relationship("User")


class AlertRule(Base):
    """B7 — a user-saved threshold rule, e.g. "BPI < 40 → notify".

    Evaluated against the live KPI engines for the rule's scope (a specific brand,
    or the user's framework brands when brand_id is null). A breach creates a
    `threshold_rule` Alert. In-app only for now (delivery = B8, deferred).
    """
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    metric: Mapped[RuleMetric] = mapped_column(Enum(RuleMetric), nullable=False)
    operator: Mapped[RuleOperator] = mapped_column(Enum(RuleOperator), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    # Null brand_id = evaluate across the owner's framework brands (bounded set).
    brand_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("brands.id", ondelete="CASCADE"), nullable=True
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        Enum(AlertSeverity), nullable=False, default=AlertSeverity.medium
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[Optional["User"]] = relationship("User")
