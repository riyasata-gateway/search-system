from celery import shared_task

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)


@shared_task(name="workers.ingestion_worker.run_all_ingestion", bind=True)
def run_all_ingestion(self, search_topic_id: int = None):
    """
    Master ingestion task — triggers all enabled source collectors.
    In production (Azure), individual Azure Function Timer Triggers
    call each source-specific task directly instead of this master task.
    This master task is used for manual full-refresh or local dev.
    """
    if not settings.DPIA_PROCESSING_ENABLED:
        logger.warning("ingestion_blocked", reason="DPIA_PROCESSING_ENABLED=false")
        return {"status": "blocked"}

    from ingestion.tasks import (
        collect_google_trends,
        collect_reddit,
        collect_rss_news,
        collect_forums,
        collect_youtube,
    )

    results = {}
    results["google_trends"] = collect_google_trends.delay(search_topic_id=search_topic_id).id
    results["rss_news"] = collect_rss_news.delay(search_topic_id=search_topic_id).id
    results["forums"] = collect_forums.delay(search_topic_id=search_topic_id).id

    if settings.REDDIT_CLIENT_ID:
        results["reddit"] = collect_reddit.delay(search_topic_id=search_topic_id).id

    if settings.YOUTUBE_API_KEY:
        results["youtube"] = collect_youtube.delay(search_topic_id=search_topic_id).id

    logger.info("run_all_ingestion_dispatched", task_ids=results)
    return results
