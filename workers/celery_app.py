from celery import Celery

from core.config import settings

celery_app = Celery(
    "pharmawatch",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "ingestion.tasks",
        "workers.processing_worker",
        "workers.ingestion_worker",
        "workers.streaming_worker",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Brussels",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,
)

# Azure Functions replace this schedule in production.
# beat_schedule kept for local dev only (docker-compose --profile dev).
celery_app.conf.beat_schedule = {
    "collect-google-trends-daily": {
        "task": "ingestion.tasks.collect_google_trends",
        "schedule": 86400,
    },
    "collect-reddit-6h": {
        "task": "ingestion.tasks.collect_reddit",
        "schedule": 21600,
    },
    "collect-rss-news-4h": {
        "task": "ingestion.tasks.collect_rss_news",
        "schedule": 14400,
    },
    "process-pending-mentions-15min": {
        "task": "workers.processing_worker.process_pending_mentions",
        "schedule": 900,
    },
    "generate-recommendations-daily": {
        "task": "workers.processing_worker.generate_all_recommendations",
        "schedule": 86400,
    },
    "expire-raw-mentions-daily": {
        "task": "core.tasks.expire_raw_mentions",
        "schedule": 86400,
    },

    # ── TDAH real-time streaming layer ──────────────────────────────────────
    # The framework requires "ingestion continue, aucun signal ne se perd".
    # Short-window pulses keep the bus warm without exhausting rate limits.
    "stream-news-pulse-60s": {
        "task": "workers.streaming_worker.stream_news_pulse",
        "schedule": 60,
    },
    "stream-forums-pulse-5min": {
        "task": "workers.streaming_worker.stream_forums_pulse",
        "schedule": 300,
    },
    "sweep-anomalies-5min": {
        "task": "workers.streaming_worker.sweep_anomalies",
        "schedule": 300,
    },
    "sweep-momentum-15min": {
        "task": "workers.streaming_worker.sweep_high_momentum",
        "schedule": 900,
    },
}
