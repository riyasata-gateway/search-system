import enum
from typing import List, Optional

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


class TimeWindow(str, enum.Enum):
    days_7 = "7d"
    days_30 = "30d"
    days_90 = "90d"


class SearchTopic(Base, TimestampMixin):
    """
    Module 1 — Search Setup.
    Each user configures a brand/topic to monitor, with market, languages,
    sources, competitors, and time window.
    """
    __tablename__ = "search_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("brands.id", ondelete="SET NULL"), nullable=True
    )
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("product_categories.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    countries: Mapped[List[str]] = mapped_column(ARRAY(String(2)), nullable=False)
    languages: Mapped[List[str]] = mapped_column(ARRAY(String(5)), nullable=False)
    time_window: Mapped[TimeWindow] = mapped_column(
        Enum(TimeWindow), nullable=False, default=TimeWindow.days_30
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    competitors: Mapped[List["SearchTopicCompetitor"]] = relationship(
        "SearchTopicCompetitor", back_populates="search_topic", cascade="all, delete-orphan"
    )
    sources: Mapped[List["SearchTopicSource"]] = relationship(
        "SearchTopicSource", back_populates="search_topic", cascade="all, delete-orphan"
    )


class SearchTopicCompetitor(Base):
    """
    Competitors configured for a specific search topic/brand monitoring setup.
    """
    __tablename__ = "search_topic_competitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_topic_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("search_topics.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )

    search_topic: Mapped["SearchTopic"] = relationship("SearchTopic", back_populates="competitors")
    brand: Mapped["Brand"] = relationship("Brand")


class SearchTopicSource(Base):
    """
    Source types enabled for a specific search topic.
    Enforces per-topic source policy: which Tier sources are active.
    """
    __tablename__ = "search_topic_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_topic_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("search_topics.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    search_topic: Mapped["SearchTopic"] = relationship("SearchTopic", back_populates="sources")
