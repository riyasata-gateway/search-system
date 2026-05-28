from functools import lru_cache
from typing import Optional, Tuple

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

TOPIC_LABELS = [
    "price",
    "efficacy",
    "side effect",
    "availability",
    "packaging",
    "recommendation",
    "general",
]

INTENT_LABELS = [
    "complaint",
    "question",
    "purchase intent",
    "comparison",
    "recommendation",
    "other",
]

TOPIC_NORMALISE = {
    "side effect": "side_effect",
    "purchase intent": "purchase_intent",
}


@lru_cache(maxsize=1)
def _get_pipeline():
    from transformers import pipeline
    return pipeline(
        "zero-shot-classification",
        model=settings.TOPIC_MODEL,
        device=-1,
    )


def classify_topic(text: str) -> Tuple[Optional[str], float]:
    """
    Zero-shot topic classification using BART-MNLI.
    Returns (topic_label, confidence_score).
    """
    if not text or len(text.strip()) < 10:
        return "general", 0.5
    try:
        pipe = _get_pipeline()
        result = pipe(text[:512], candidate_labels=TOPIC_LABELS, multi_label=False)
        if result:
            label = result["labels"][0]
            score = float(result["scores"][0])
            normalised = TOPIC_NORMALISE.get(label, label)
            return normalised, score
        return "general", 0.5
    except Exception as exc:
        logger.warning("topic_classification_failed", error=str(exc))
        return "general", 0.5


def classify_intent(text: str) -> Tuple[Optional[str], float]:
    """
    Zero-shot intent classification.
    Returns (intent_label, confidence_score).
    """
    if not text or len(text.strip()) < 10:
        return "other", 0.5
    try:
        pipe = _get_pipeline()
        result = pipe(text[:512], candidate_labels=INTENT_LABELS, multi_label=False)
        if result:
            label = result["labels"][0]
            score = float(result["scores"][0])
            normalised = TOPIC_NORMALISE.get(label, label)
            return normalised, score
        return "other", 0.5
    except Exception as exc:
        logger.warning("intent_classification_failed", error=str(exc))
        return "other", 0.5
