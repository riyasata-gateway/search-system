"""Search audit — persists every /search/live, /search/ai and /search/semantic call.

Powers: replay, caching, governance/audit (what evidence did the LLM see?),
analytics on what users actually look for.
"""
import enum
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base
from models.mention import Sentiment


class SearchMode(str, enum.Enum):
    live = "live"
    ai = "ai"
    semantic = "semantic"


class SearchQuery(Base):
    __tablename__ = "search_queries"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mode: Mapped[SearchMode] = mapped_column(Enum(SearchMode), nullable=False, index=True)
    q: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    lang: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, index=True,
        comment="Role lens applied to this search (pharmacist/marketing/brand_manager/admin) — powers role-based analytics",
    )
    sources_requested: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    expanded_terms: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    filters: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        comment="Period, country, brand_id, etc. — kept flexible per mode",
    )
    total_results: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elapsed_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    results: Mapped[list["SearchResult"]] = relationship(
        "SearchResult", back_populates="query", cascade="all, delete-orphan",
    )
    ai_answer: Mapped[Optional["AIAnswer"]] = relationship(
        "AIAnswer", back_populates="query", uselist=False, cascade="all, delete-orphan",
    )


class SearchResult(Base):
    __tablename__ = "search_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("search_queries.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sentiment: Mapped[Optional[Sentiment]] = mapped_column(Enum(Sentiment), nullable=True)
    topic: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    risk_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    score: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 5), nullable=True,
        comment="Cosine score for semantic mode; null otherwise",
    )
    mention_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("mentions.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Only set when result was matched to a stored mention (semantic mode)",
    )
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    query: Mapped["SearchQuery"] = relationship("SearchQuery", back_populates="results")


class AIAnswer(Base):
    __tablename__ = "ai_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("search_queries.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    sentiment_summary: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    disclaimer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    grounding_sources: Mapped[Optional[list]] = mapped_column(
        JSONB, nullable=True,
        comment="List of {ref, source_url, source_type, snippet} — the evidence the LLM saw",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    query: Mapped["SearchQuery"] = relationship("SearchQuery", back_populates="ai_answer")