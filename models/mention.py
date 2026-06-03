import enum
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class EntityType(str, enum.Enum):
    brand = "brand"
    product = "product"
    competitor = "competitor"
    ingredient = "ingredient"
    category = "category"


class Sentiment(str, enum.Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class Topic(str, enum.Enum):
    price = "price"
    efficacy = "efficacy"
    side_effect = "side_effect"
    availability = "availability"
    packaging = "packaging"
    recommendation = "recommendation"
    general = "general"


class Intent(str, enum.Enum):
    complaint = "complaint"
    question = "question"
    purchase_intent = "purchase_intent"
    comparison = "comparison"
    recommendation = "recommendation"
    other = "other"


class RiskType(str, enum.Enum):
    adverse_event = "adverse_event"
    misinformation = "misinformation"
    counterfeit = "counterfeit"
    shortage = "shortage"
    none = "none"


class ReviewStatus(str, enum.Enum):
    pending = "pending"
    reviewed = "reviewed"
    escalated = "escalated"
    dismissed = "dismissed"


class Mention(Base):
    __tablename__ = "mentions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    source_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True
    )
    source_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True, index=True)
    language: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    clean_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author_id_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="SHA-256 of original author ID — pseudonymised per GDPR"
    )
    engagement_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    query_used: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True,
        comment="The exact search query / keyword used to collect this mention — for traceability"
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retention_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="raw_text is wiped and is_deleted=true after this date per GDPR retention policy"
    )
    qdrant_point_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), nullable=True,
        comment="Link to Qdrant vector point for semantic search"
    )
    # ── Review-native fields (pharmacy product-review imports) ───────────────
    rating: Mapped[Optional[int]] = mapped_column(
        SmallInteger, nullable=True,
        comment="Star rating 1–5 for review-sourced mentions (null for non-review sources)"
    )
    brand_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    product_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    source: Mapped[Optional["DataSource"]] = relationship("DataSource")
    entities: Mapped[list["MentionEntity"]] = relationship(
        "MentionEntity", back_populates="mention", cascade="all, delete-orphan"
    )
    classification: Mapped[Optional["MentionClassification"]] = relationship(
        "MentionClassification", back_populates="mention", uselist=False, cascade="all, delete-orphan"
    )
    adverse_event_candidate: Mapped[Optional["AdverseEventCandidate"]] = relationship(
        "AdverseEventCandidate", back_populates="mention", uselist=False
    )


class MentionEntity(Base):
    __tablename__ = "mention_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("mentions.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)

    mention: Mapped["Mention"] = relationship("Mention", back_populates="entities")


class MentionClassification(Base):
    __tablename__ = "mention_classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("mentions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    sentiment: Mapped[Optional[Sentiment]] = mapped_column(Enum(Sentiment), nullable=True)
    topic: Mapped[Optional[Topic]] = mapped_column(Enum(Topic), nullable=True)
    intent: Mapped[Optional[Intent]] = mapped_column(Enum(Intent), nullable=True)
    risk_type: Mapped[RiskType] = mapped_column(
        Enum(RiskType), nullable=False, default=RiskType.none
    )
    is_adverse_event_candidate: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_prescription_promotion: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Flagged if mention promotes prescription medicine — pharma regulatory guard"
    )
    confidence_score: Mapped[Optional[float]] = mapped_column(Numeric(4, 3), nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), nullable=False, default=ReviewStatus.pending
    )
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    mention: Mapped["Mention"] = relationship("Mention", back_populates="classification")
    reviewer: Mapped[Optional["User"]] = relationship("User")
