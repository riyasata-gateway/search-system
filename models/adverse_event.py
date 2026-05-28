import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class AdverseEventReviewStatus(str, enum.Enum):
    pending = "pending"
    reviewed = "reviewed"
    escalated = "escalated"
    dismissed = "dismissed"
    reported = "reported"


class AdverseEventCandidate(Base):
    """
    Every mention flagged as a possible adverse event is stored here
    and routed to a human pharmacovigilance reviewer.
    Final decisions are NEVER made by the system — human review mandatory.
    """
    __tablename__ = "adverse_event_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("mentions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    review_status: Mapped[AdverseEventReviewStatus] = mapped_column(
        Enum(AdverseEventReviewStatus),
        nullable=False,
        default=AdverseEventReviewStatus.pending,
    )
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pharmacovigilance_ref: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True,
        comment="External pharmacovigilance system reference number after escalation"
    )
    notification_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Timestamp of email notification sent to pharmacovigilance team"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    mention: Mapped["Mention"] = relationship("Mention", back_populates="adverse_event_candidate")
    product: Mapped[Optional["Product"]] = relationship("Product")
    reviewer: Mapped[Optional["User"]] = relationship("User")
