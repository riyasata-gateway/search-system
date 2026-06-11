import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class SourceType(str, enum.Enum):
    google_trends = "google_trends"
    reddit = "reddit"
    rss = "rss"
    forum = "forum"
    youtube = "youtube"
    licensed_api = "licensed_api"
    pharmacy_import = "pharmacy_import"


class DataSource(Base, TimestampMixin):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tier: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    last_collected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Source policy / GDPR traceability ────────────────────────────────────
    is_scraping_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Set true only after verifying robots.txt and ToS allow scraping"
    )
    robots_txt_checked: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Flag to confirm robots.txt was reviewed before enabling scraping"
    )
    lawful_basis: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="GDPR lawful basis for collecting from this source (e.g. legitimate_interest)"
    )
    terms_of_service_url: Mapped[Optional[str]] = mapped_column(
        String(2048), nullable=True,
        comment="URL to the ToS document reviewed before enabling this source"
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Internal notes on why this source is included or excluded"
    )
