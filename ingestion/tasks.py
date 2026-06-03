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


def _topic_keywords(session, topic: SearchTopic) -> list:
    """Build a search-keyword list from a topic's brand, products, aliases,
    category and competitors. Returns human search terms (never raw ids)."""
    from models.brand import Brand
    from models.product import Product, ProductAlias, ProductCategory
    from models.search_topic import SearchTopicCompetitor

    keywords: list[str] = []

    def _add(value):
        if value and value.strip() and value.strip().lower() not in {k.lower() for k in keywords}:
            keywords.append(value.strip())

    brand_ids = []
    if topic.brand_id:
        brand_ids.append(topic.brand_id)
    brand_ids += [
        c.brand_id for c in session.execute(
            select(SearchTopicCompetitor).where(SearchTopicCompetitor.search_topic_id == topic.id)
        ).scalars().all()
    ]

    if brand_ids:
        for name in session.execute(
            select(Brand.name).where(Brand.id.in_(brand_ids))
        ).scalars().all():
            _add(name)

        product_ids = session.execute(
            select(Product.id).where(Product.brand_id.in_(brand_ids))
        ).scalars().all()
        for name in session.execute(
            select(Product.name).where(Product.brand_id.in_(brand_ids))
        ).scalars().all():
            _add(name)
        if product_ids:
            for alias in session.execute(
                select(ProductAlias.alias).where(ProductAlias.product_id.in_(product_ids))
            ).scalars().all():
                _add(alias)

    if topic.category_id:
        cat = session.get(ProductCategory, topic.category_id)
        if cat:
            for n in (cat.name_en, cat.name_fr, cat.name_nl, cat.name_de):
                _add(n)

    return keywords


def _resolve_collection_params(search_topic_id: Optional[int], source_type: str, default_keywords: list):
    """Resolve (keywords, countries, languages, skip) for a collector run.

    When a `search_topic_id` is supplied the topic's own configuration drives
    collection: its keywords (brand/product/alias/category/competitors), its
    markets and languages, and its per-source on/off switch. Without a topic we
    fall back to the global defaults so periodic full-refresh keeps working.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    countries = settings.SUPPORTED_COUNTRIES
    languages = settings.SUPPORTED_LANGUAGES

    if search_topic_id is None:
        return default_keywords, countries, languages, False

    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as session:
        topic = session.get(SearchTopic, search_topic_id)
        if topic is None:
            logger.warning("collection_topic_not_found", search_topic_id=search_topic_id)
            return default_keywords, countries, languages, False

        from models.search_topic import SearchTopicSource
        srcs = session.execute(
            select(SearchTopicSource).where(SearchTopicSource.search_topic_id == topic.id)
        ).scalars().all()
        # if the topic declares sources, honour its on/off switch for this one
        if srcs and not any(s.source_type == source_type and s.is_enabled for s in srcs):
            return default_keywords, countries, languages, True

        keywords = _topic_keywords(session, topic) or default_keywords
        if topic.countries:
            countries = topic.countries
        if topic.languages:
            languages = topic.languages
        return keywords, countries, languages, False


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


@shared_task(name="ingestion.tasks.ingest_live_results", bind=True, max_retries=2)
def ingest_live_results(self, results: Optional[list] = None):
    """Governed async ingest of *live-search* results into the mentions corpus.

    Live Search is no-write on the request path; this task lets a search also
    enrich the canonical corpus by routing its results through the SAME persist
    pipeline the connectors use (`_persist_mentions` → dedup + retention + bus).
    The periodic `process_pending_mentions` task then classifies / entity-resolves
    / risk-flags them exactly like connector data. DPIA-gated like all ingest.
    """
    if not settings.DPIA_PROCESSING_ENABLED:
        logger.warning("ingestion_blocked", reason="DPIA_PROCESSING_ENABLED=false")
        return {"status": "blocked", "reason": "DPIA not enabled"}

    from collections import defaultdict

    by_source: dict = defaultdict(list)
    for r in (results or []):
        text = (r.get("raw_text") or "").strip()
        if not text:
            continue
        published = r.get("published_at")
        if isinstance(published, str):
            try:
                published = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                published = None
        rm = RawMention(
            source_type=r.get("source_type") or "live_search",
            source_url=r.get("source_url"),
            country=r.get("country"),
            language=r.get("language"),
            published_at=published,
            raw_text=text,
            query_used=r.get("query_used") or "",
            author_id=None,
            engagement_count=r.get("engagement_count"),
            metadata=r.get("metadata") or {},
        )
        by_source[rm.source_type].append(rm)

    total = 0
    for source_type, rms in by_source.items():
        total += _persist_mentions(rms, source_type)
    logger.info("ingest_live_results_done", saved=total, sources=list(by_source.keys()))
    return {"saved": total}


@shared_task(name="ingestion.tasks.collect_google_trends", bind=True, max_retries=3)
def collect_google_trends(self, search_topic_id: Optional[int] = None):
    if not settings.DPIA_PROCESSING_ENABLED:
        logger.warning("ingestion_blocked", reason="DPIA_PROCESSING_ENABLED=false")
        return {"status": "blocked", "reason": "DPIA not enabled"}

    from ingestion.connectors.google_trends import GoogleTrendsConnector
    import asyncio

    keywords, countries, languages, skip = _resolve_collection_params(
        search_topic_id, "google_trends",
        ["paracetamol", "ibuprofen", "dafalgan", "probiotique", "antihistamine"],
    )
    if skip:
        return {"status": "skipped", "reason": "source disabled for this topic"}

    connector = GoogleTrendsConnector()
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

    keywords, countries, languages, skip = _resolve_collection_params(
        search_topic_id, "reddit",
        ["pharmacie", "médicament", "dafalgan", "paracetamol", "ibuprofen"],
    )
    if skip:
        return {"status": "skipped", "reason": "source disabled for this topic"}
    raw = asyncio.get_event_loop().run_until_complete(
        connector.collect(keywords, countries, languages)
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
    keywords, countries, languages, skip = _resolve_collection_params(
        search_topic_id, "rss",
        ["pharmacie", "médicament", "vaccin", "santé", "prescription"],
    )
    if skip:
        return {"status": "skipped", "reason": "source disabled for this topic"}
    raw = asyncio.get_event_loop().run_until_complete(
        connector.collect(keywords, countries, languages)
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
    keywords, countries, languages, skip = _resolve_collection_params(
        search_topic_id, "forum",
        ["médicament", "pharmacie", "allergie", "douleur", "digestion"],
    )
    if skip:
        return {"status": "skipped", "reason": "source disabled for this topic"}
    raw = asyncio.get_event_loop().run_until_complete(
        connector.collect(keywords, countries, languages)
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

    keywords, countries, languages, skip = _resolve_collection_params(
        search_topic_id, "youtube",
        ["pharmacie conseil", "médicament avis", "dafalgan review"],
    )
    if skip:
        return {"status": "skipped", "reason": "source disabled for this topic"}
    raw = asyncio.get_event_loop().run_until_complete(
        connector.collect(keywords, countries, languages)
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
