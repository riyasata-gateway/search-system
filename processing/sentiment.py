from functools import lru_cache
from typing import Dict, Optional, Tuple

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

LABEL_MAP = {
    "positive": "positive",
    "negative": "negative",
    "neutral": "neutral",
    "LABEL_0": "negative",
    "LABEL_1": "neutral",
    "LABEL_2": "positive",
    "POS": "positive",
    "NEG": "negative",
    "NEU": "neutral",
}


@lru_cache(maxsize=1)
def _get_pipeline():
    from transformers import pipeline
    return pipeline(
        "text-classification",
        model=settings.SENTIMENT_MODEL,
        device=-1,
        truncation=True,
        max_length=512,
    )


def classify_sentiment(text: str) -> Tuple[Optional[str], float]:
    """
    Returns (sentiment_label, confidence_score).
    Uses XLM-RoBERTa multilingual model — handles FR/NL/EN/DE natively.
    Note: A negative sentence about side effects is medically significant,
    not just 'bad sentiment'. Callers must treat negative + side_effect
    topic together as a possible adverse event candidate.
    """
    if not text or len(text.strip()) < 5:
        return None, 0.0
    try:
        pipe = _get_pipeline()
        result = pipe(text[:512])
        if result and isinstance(result, list):
            top = result[0]
            label = LABEL_MAP.get(top["label"], top["label"].lower())
            score = float(top["score"])
            return label, score
        return None, 0.0
    except Exception as exc:
        logger.warning("sentiment_classification_failed", error=str(exc))
        return None, 0.0
