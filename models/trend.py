import enum
from datetime import date
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class TrendPeriod(str, enum.Enum):
    days_7 = "7d"
    days_30 = "30d"
    days_90 = "90d"


class TrendSignal(Base):
    """
    Trend scoring per entity, country, region, city, source, and period.
    City/region fields added to satisfy spec example:
    'High search interest in Brussels for hay fever products this week.'
    engagement_count_weighted used in trend score so high-engagement posts
    contribute more to signals.
    """
    __tablename__ = "trend_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True, index=True)
    region: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True,
        comment="Sub-national region, e.g. Wallonia, Flanders, Île-de-France"
    )
    city: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True,
        comment="City-level demand signal, e.g. Brussels, Paris, Liège"
    )
    language: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    signal_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    score: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    relative_change: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 4), nullable=True,
        comment="% change vs previous equivalent period"
    )
    engagement_count_weighted: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True,
        comment="Engagement-weighted signal score — high-engagement posts count more"
    )
    period: Mapped[TrendPeriod] = mapped_column(
        Enum(TrendPeriod), nullable=False, default=TrendPeriod.days_30
    )
    mention_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "entity_type", "entity_id", "country", "region", "city",
            "source_type", "signal_date", "period",
            name="uq_trend_signal"
        ),
    )
