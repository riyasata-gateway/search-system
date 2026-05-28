from datetime import datetime, timezone
from typing import Optional

from celery import shared_task
from sqlalchemy import select

from core.config import settings
from core.event_bus import Channel, publish_event
from core.logging import get_logger
from ingestion.deduplication import compute_text_hash, is_text_too_short, sanitise_text
from ingestion.connectors.base import RawMention
from models.mention import Mention
from models.search_topic import SearchTopic

logger = get_logger(__name__)


def _get_keywords_for_topic(topic: SearchTopic) -> list:
    from models.brand import Brand
    from models.product import Product, ProductAlias
    keywords = []
    if topic.brand_id:
        keywords.append(str(topic.brand_id))
    return keywords


def _persist_mentions(raw_mentions: list, source_type: str) -> int:
    """Synchronous helper — runs inside a Celery worker (sync SQLAlchemy).

    On each newly-persisted mention, publishes an `events:mentions` payload
    so SSE subscribers can render it in real time. Publishing is fire-and-
    forget — failures don't roll back the persist.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(settings.DATABASE_SYNC_URL)
    saved = 0
    new_mentions_for_bus: list[dict] = []

    with Session(engine) as session:
        for raw in raw_mentions:
            if is_text_too_short(raw.raw_text):
                continue

            clean = sanitise_text(raw.raw_text)
            text_hash = compute_text_hash(raw)

            existing = session.execute(
                select(Mention).where(Mention.text_hash == text_hash)
            ).scalar_one_or_none()

            if existing:
                continue

            retention_date = None
            if settings.MENTION_RETENTION_DAYS:
                from datetime import timedelta
                retention_date = datetime.now(timezone.utc) + timedelta(days=settings.MENTION_RETENTION_DAYS)

            mention = Mention(
                source_type=raw.source_type,
                source_url=raw.source_url,
                country=raw.country,
                language=raw.language,
                published_at=raw.published_at,
                collected_at=datetime.now(timezone.utc),
                text_hash=text_hash,
                raw_text=raw.raw_text,
                clean_text=clean,
                author_id_hash=raw.author_id,
                engagement_count=raw.engagement_count,
                query_used=raw.query_used,
                retention_expires_at=retention_date,
            )
            session.add(mention)
            session.flush()  # populate mention.id for the bus payload
            new_mentions_for_bus.append({
                "id": mention.id,
                "source_type": mention.source_type,
                "source_url": mention.source_url,
                "country": mention.country,
                "language": mention.language,
                "published_at": mention.published_at.isoformat() if mention.published_at else None,
                "text": (mention.clean_text or mention.raw_text or "")[:400],
                "query_used": mention.query_used,
            })
            saved += 1

        session.commit()

    # Fan out to the streaming bus AFTER commit — never publish ghosts.
    for payload in new_mentions_for_bus:
        publish_event(Channel.MENTIONS, {"event": "mention.created", **payload})

    return saved


@shared_task(name="ingestion.tasks.collect_google_trends", bind=True, max_retries=3)
def collect_google_trends(self, search_topic_id: Optional[int] = None):
    if not settings.DPIA_PROCESSING_ENABLED:
        logger.warning("ingestion_blocked", reason="DPIA_PROCESSING_ENABLED=false")
        return {"status": "blocked", "reason": "DPIA not enabled"}

    from ingestion.connectors.google_trends import GoogleTrendsConnector
    import asyncio

    connector = GoogleTrendsConnector()
    keywords = ["paracetamol", "ibuprofen", "dafalgan", "probiotique", "antihistamine"]
    countries = settings.SUPPORTED_COUNTRIES
    languages = settings.SUPPORTED_LANGUAGES

    raw = asyncio.get_event_loop().run_until_complete(
        connector.collect(keywords, countries, languages)
    )
    saved = _persist_mentions(raw, "google_trends")
    logger.info("collect_google_trends_done", saved=saved)
    return {"saved": saved}


@shared_task(name="ingestion.tasks.collect_reddit", bind=True, max_retries=3)
def collect_reddit(self, search_topic_id: Optional[int] = None):
    if not settings.DPIA_PROCESSING_ENABLED:
        return {"status": "blocked"}

    from ingestion.connectors.reddit import RedditConnector
    import asyncio

    connector = RedditConnector()
    if not connector.is_available():
        return {"status": "skipped", "reason": "Reddit credentials not configured"}

    keywords = ["pharmacie", "médicament", "dafalgan", "paracetamol", "ibuprofen"]
    raw = asyncio.get_event_loop().run_until_complete(
        connector.collect(keywords, settings.SUPPORTED_COUNTRIES, settings.SUPPORTED_LANGUAGES)
    )
    saved = _persist_mentions(raw, "reddit")
    logger.info("collect_reddit_done", saved=saved)
    return {"saved": saved}


@shared_task(name="ingestion.tasks.collect_rss_news", bind=True, max_retries=3)
def collect_rss_news(self, search_topic_id: Optional[int] = None):
    if not settings.DPIA_PROCESSING_ENABLED:
        return {"status": "blocked"}

    from ingestion.connectors.rss_news import RSSNewsConnector
    import asyncio

    connector = RSSNewsConnector()
    keywords = ["pharmacie", "médicament", "vaccin", "santé", "prescription"]
    raw = asyncio.get_event_loop().run_until_complete(
        connector.collect(keywords, settings.SUPPORTED_COUNTRIES, settings.SUPPORTED_LANGUAGES)
    )
    saved = _persist_mentions(raw, "rss")
    logger.info("collect_rss_news_done", saved=saved)
    return {"saved": saved}


@shared_task(name="ingestion.tasks.collect_forums", bind=True, max_retries=2)
def collect_forums(self, search_topic_id: Optional[int] = None):
    if not settings.DPIA_PROCESSING_ENABLED:
        return {"status": "blocked"}

    from ingestion.connectors.forum_scraper import ForumScraperConnector
    import asyncio

    connector = ForumScraperConnector()
    keywords = ["médicament", "pharmacie", "allergie", "douleur", "digestion"]
    raw = asyncio.get_event_loop().run_until_complete(
        connector.collect(keywords, settings.SUPPORTED_COUNTRIES, settings.SUPPORTED_LANGUAGES)
    )
    saved = _persist_mentions(raw, "forum")
    logger.info("collect_forums_done", saved=saved)
    return {"saved": saved}


@shared_task(name="ingestion.tasks.collect_youtube", bind=True, max_retries=2)
def collect_youtube(self, search_topic_id: Optional[int] = None):
    if not settings.DPIA_PROCESSING_ENABLED:
        return {"status": "blocked"}

    from ingestion.connectors.youtube import YouTubeConnector
    import asyncio

    connector = YouTubeConnector()
    if not connector.is_available():
        return {"status": "skipped", "reason": "YOUTUBE_API_KEY not configured"}

    keywords = ["pharmacie conseil", "médicament avis", "dafalgan review"]
    raw = asyncio.get_event_loop().run_until_complete(
        connector.collect(keywords, settings.SUPPORTED_COUNTRIES, settings.SUPPORTED_LANGUAGES)
    )
    saved = _persist_mentions(raw, "youtube")
    logger.info("collect_youtube_done", saved=saved)
    return {"saved": saved}


@shared_task(name="ingestion.tasks.import_pharmacy_file", bind=True)
def import_pharmacy_file(self, pharmacy_id: int, filename: str, content: str):
    from ingestion.connectors.pharmacy_import import parse_pharmacy_file
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models.pharmacy import PharmacySale
    from models.product import Product

    records, errors = parse_pharmacy_file(content, filename)
    if errors:
        logger.warning("pharmacy_import_errors", pharmacy_id=pharmacy_id, errors=errors[:10])

    engine = create_engine(settings.DATABASE_SYNC_URL)
    saved = 0
    with Session(engine) as session:
        for rec in records:
            product = session.execute(
                select(Product).where(Product.cnk == rec["cnk"])
            ).scalar_one_or_none()

            if not product:
                logger.warning("pharmacy_import_cnk_not_found", cnk=rec["cnk"])
                continue

            sale = PharmacySale(
                pharmacy_id=pharmacy_id,
                product_id=product.id,
                quantity=rec["quantity"],
                revenue=rec["revenue"],
                sale_date=rec["sale_date"],
            )
            session.merge(sale)
            saved += 1
        session.commit()

    logger.info("pharmacy_import_done", pharmacy_id=pharmacy_id, saved=saved, errors=len(errors))
    return {"saved": saved, "errors": len(errors), "error_details": errors[:20]}


@shared_task(name="core.tasks.expire_raw_mentions")
def expire_raw_mentions():
    """GDPR retention: wipe raw_text and mark is_deleted for expired mentions."""
    from sqlalchemy import create_engine, update
    from sqlalchemy.orm import Session

    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as session:
        now = datetime.now(timezone.utc)
        result = session.execute(
            update(Mention)
            .where(
                Mention.retention_expires_at <= now,
                Mention.is_deleted == False,
            )
            .values(raw_text=None, clean_text=None, is_deleted=True)
        )
        session.commit()
        expired = result.rowcount

    logger.info("gdpr_retention_expired", expired=expired)
    return {"expired": expired}
