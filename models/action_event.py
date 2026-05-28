"""Action telemetry — the flywheel closure model.

Every user action on a surfaced recommendation, alert, or AI suggestion is
logged here. Aggregations over this table feed back into the D-layer signal
weighting (e.g. boost trend score for categories with high acceptance rates),
closing the loop the TDAH framework calls "chaque action enrichit la donnée".

Decisions are kept granular so we can distinguish "ignored entirely" from
"viewed but skipped" from "viewed and acted on outside the app".
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class ActionSubjectType(str, enum.Enum):
    recommendation = "recommendation"
    alert = "alert"
    adverse_event = "adverse_event"
    ai_suggestion = "ai_suggestion"
    trend_signal = "trend_signal"
    bpi_score = "bpi_score"


class ActionDecision(str, enum.Enum):
    viewed = "viewed"
    accepted = "accepted"
    skipped = "skipped"
    acted_upon = "acted_upon"
    dismissed = "dismissed"
    snoozed = "snoozed"


class ActionEvent(Base):
    __tablename__ = "action_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subject_type: Mapped[ActionSubjectType] = mapped_column(
        Enum(ActionSubjectType), nullable=False, index=True
    )
    subject_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="String to accept both numeric IDs and UUIDs (mentions are UUIDs)",
    )
    decision: Mapped[ActionDecision] = mapped_column(
        Enum(ActionDecision), nullable=False, index=True
    )
    context: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        comment="Captured payload at decision time — BPI score, trend % etc.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True
    )

    user: Mapped[Optional["User"]] = relationship("User")
