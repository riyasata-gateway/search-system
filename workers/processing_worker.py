from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from core.logging import get_logger
from models.mention import Mention, MentionClassification, MentionEntity

logger = get_logger(__name__)


def _get_sync_session() -> Session:
    engine = create_engine(settings.DATABASE_SYNC_URL)
    return Session(engine)


@shared_task(name="workers.processing_worker.process_pending_mentions", bind=True, max_retries=2)
def process_pending_mentions(self, batch_size: int = 100):
    """
    NLP pipeline per mention:
    1. Language detection
    2. Entity resolution
    3. Sentiment classification
    4. Topic classification
    5. Risk / adverse event detection
    6. Embedding + Qdrant upsert
    7. Alert engine check
    """
    from processing.language_detection import detect_language
    from processing.entity_resolution import resolve
    from processing.sentiment import classify_sentiment
    from processing.topic_classifier import classify_topic, classify_intent
    from processing.risk_detector import detect_risk
    from processing.embeddings import upsert_mention_embedding
    from intelligence.alert_engine import process_mention_alerts

    with _get_sync_session() as db:
        unprocessed = db.execute(
            select(Mention)
            .outerjoin(MentionClassification, MentionClassification.mention_id == Mention.id)
            .where(
                MentionClassification.id.is_(None),
                Mention.is_deleted == False,
                Mention.clean_text.isnot(None),
            )
            .limit(batch_size)
        ).scalars().all()

        processed = 0
        for mention in unprocessed:
            try:
                text = mention.clean_text or ""

                lang = mention.language or detect_language(text) or "en"
                if mention.language is None:
                    mention.language = lang

                entities = resolve(text, lang=lang, country=mention.country)
                for ent in entities:
                    existing_ent = db.execute(
                        select(MentionEntity).where(
                            MentionEntity.mention_id == mention.id,
                            MentionEntity.entity_type == ent["entity_type"],
                            MentionEntity.entity_id == ent["entity_id"],
                        )
                    ).scalar_one_or_none()
                    if not existing_ent:
                        db.add(MentionEntity(
                            mention_id=mention.id,
                            entity_type=ent["entity_type"],
                            entity_id=ent["entity_id"],
                            confidence=ent["confidence"],
                        ))

                sentiment, sent_score = classify_sentiment(text)
                topic, topic_score = classify_topic(text)
                intent, intent_score = classify_intent(text)
                risk = detect_risk(text, lang=lang)

                avg_confidence = round((sent_score + topic_score) / 2, 4)

                classification = MentionClassification(
                    mention_id=mention.id,
                    sentiment=sentiment,
                    topic=topic,
                    intent=intent,
                    risk_type=risk.risk_type,
                    is_adverse_event_candidate=risk.is_adverse_event_candidate,
                    is_prescription_promotion=risk.is_prescription_promotion,
                    confidence_score=avg_confidence,
                    model_name=f"{settings.SENTIMENT_MODEL}|{settings.TOPIC_MODEL}",
                )
                db.add(classification)
                db.flush()

                qdrant_id = upsert_mention_embedding(
                    mention_id=str(mention.id),
                    text=text,
                    metadata={
                        "source_type": mention.source_type,
                        "country": mention.country,
                        "language": lang,
                    },
                )
                if qdrant_id:
                    mention.qdrant_point_id = qdrant_id

                process_mention_alerts(db, mention.id, {
                    "risk_type": risk.risk_type,
                    "is_adverse_event_candidate": risk.is_adverse_event_candidate,
                    "is_prescription_promotion": risk.is_prescription_promotion,
                    "matched_patterns_str": ", ".join(risk.matched_patterns[:5]),
                })

                processed += 1

            except Exception as exc:
                logger.error("mention_processing_failed", mention_id=str(mention.id), error=str(exc))

        db.commit()
        logger.info("process_pending_mentions_done", processed=processed)
        return {"processed": processed}


@shared_task(name="workers.processing_worker.generate_all_recommendations", bind=True)
def generate_all_recommendations(self):
    """Generate pharmacist recommendations for all active pharmacies."""
    from intelligence.pharmacist_recommender import generate_recommendations
    from models.pharmacy import Pharmacy

    with _get_sync_session() as db:
        pharmacies = db.execute(select(Pharmacy)).scalars().all()
        total = 0
        for pharmacy in pharmacies:
            total += generate_recommendations(db, pharmacy.id)

    logger.info("generate_all_recommendations_done", total_new=total)
    return {"total_new": total}


@shared_task(name="workers.processing_worker.compute_all_trend_signals", bind=True)
def compute_all_trend_signals(self):
    """Compute trend signals for all configured periods."""
    from intelligence.trend_engine import compute_trend_signals
    from models.trend import TrendPeriod

    with _get_sync_session() as db:
        for period in TrendPeriod:
            compute_trend_signals(db, period)

    logger.info("compute_all_trend_signals_done")
    return {"status": "done"}
