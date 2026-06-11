"""
Core Celery tasks — GDPR retention enforcement and housekeeping.
These tasks are NOT source-specific and run independently of ingestion pipelines.
"""

from datetime import datetime, timedelta, timezone

from celery import shared_task
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)


def _get_sync_session() -> Session:
    engine = create_engine(settings.DATABASE_SYNC_URL)
    return Session(engine)


@shared_task(name="core.tasks.expire_raw_mentions", bind=True)
def expire_raw_mentions(self) -> dict:
    """
    GDPR retention enforcement:
    - Soft-deletes raw mention text (clean_text, raw fields) after MENTION_RETENTION_DAYS
    - Preserves aggregated trend signals (no personal data) for AGGREGATE_RETENTION_DAYS
    - Sets is_deleted=True on expired mentions (hard delete only via separate erasure task)

    This task implements the data minimisation principle under GDPR Art. 5(1)(e).
    """
    from models.mention import Mention

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.MENTION_RETENTION_DAYS)

    with _get_sync_session() as db:
        result = db.execute(
            update(Mention)
            .where(
                Mention.published_at < cutoff,
                Mention.is_deleted == False,
            )
            .values(
                is_deleted=True,
                raw_text=None,
                clean_text=None,
            )
            .execution_options(synchronize_session="fetch")
        )
        expired_count = result.rowcount
        db.commit()

    logger.info(
        "gdpr_mention_retention_enforced",
        expired_count=expired_count,
        cutoff=cutoff.isoformat(),
        retention_days=settings.MENTION_RETENTION_DAYS,
    )
    return {"expired_count": expired_count, "cutoff": cutoff.isoformat()}
