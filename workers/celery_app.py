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

# No scheduler. By product decision there is NO background/scheduled ingestion:
# all data collection is on-demand (live search) or manual (scripts/ingest_*).
# The Celery tasks remain importable so they can be invoked explicitly, but
# nothing is scheduled — running `celery beat` would do nothing.
celery_app.conf.beat_schedule = {}
