"""High-frequency streaming ingestion worker.

The TDAH framework requires "ingestion continue, aucun signal ne se perd"
— continuous ingestion so no signal is lost. We meet that requirement
without giving up the existing scheduled batches by:

  • Running short-window polls every 60–300s for low-latency sources (news,
    forums) — the result is published to the event bus the moment a row is
    persisted (see `ingestion.tasks._persist_mentions`).
  • Adding a periodic anomaly sweep that emits signal events when something
    starts trending sharply.

We keep the existing 4–6h Celery beat tasks for sources that rate-limit
hard (Google Trends, Reddit, YouTube) so we don't burn quota.
"""
from celery import shared_task

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)


@shared_task(name="workers.streaming_worker.stream_news_pulse", bind=True)
def stream_news_pulse(self):
    """Short-window Google-News fetch — every ~60 s in production.

    Reuses the existing news collector but with a tight time-window so the
    feed stays warm. The collector itself dedupes by text_hash, so duplicate
    fetches are cheap.
    """
    if not settings.DPIA_PROCESSING_ENABLED:
        return {"status": "blocked"}
    from ingestion.tasks import collect_rss_news
    return {"status": "dispatched", "task_id": collect_rss_news.delay().id}


@shared_task(name="workers.streaming_worker.stream_forums_pulse", bind=True)
def stream_forums_pulse(self):
    """Short-window forum scrape — every ~5 min."""
    if not settings.DPIA_PROCESSING_ENABLED:
        return {"status": "blocked"}
    from ingestion.tasks import collect_forums
    return {"status": "dispatched", "task_id": collect_forums.delay().id}


@shared_task(name="workers.streaming_worker.sweep_anomalies", bind=True)
def sweep_anomalies(self):
    """Periodic anomaly scan that publishes signal events for SSE subscribers."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from intelligence.anomaly import scan_anomalies

    engine = create_engine(settings.DATABASE_SYNC_URL)
    found = 0
    with Session(engine) as db:
        for entity_type in ("brand", "product"):
            results = scan_anomalies(db, entity_type=entity_type, z_threshold=2.5, limit=20)
            found += len(results)
    logger.info("anomaly_sweep_complete", found=found)
    return {"found": found}


@shared_task(name="workers.streaming_worker.sweep_high_momentum", bind=True)
def sweep_high_momentum(self):
    """Periodic momentum scan — emits a signal event when a brand crosses
    momentum_score ≥ 80 (the "weak signal before competitor" threshold).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from intelligence.momentum import rank_momentum
    from core.event_bus import Channel, publish_event

    engine = create_engine(settings.DATABASE_SYNC_URL)
    fired = 0
    with Session(engine) as db:
        top = rank_momentum(db, entity_type="brand", period="30d", limit=10)
        for r in top:
            if r.momentum_score >= 80:
                publish_event(Channel.SIGNALS, {
                    "event": "signal.momentum",
                    "entity_type": r.entity_type,
                    "entity_id": r.entity_id,
                    "country": r.country,
                    "score": r.momentum_score,
                    "velocity_pct": r.velocity_pct,
                    "acceleration": r.acceleration,
                })
                fired += 1
    logger.info("momentum_sweep_complete", fired=fired)
    return {"fired": fired}
