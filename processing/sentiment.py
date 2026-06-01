"""Backwards-compat shim — sentiment is now classified by the unified
LLM classifier (processing.llm_classifier). Callers that need only the
sentiment label can keep calling `classify_sentiment(text)` and pay one
OpenAI call. Callers that need sentiment + topic + intent SHOULD call
`processing.llm_classifier.classify_mention(text)` directly to get all
three from a single API hit.
"""
from typing import Optional, Tuple

from processing.llm_classifier import classify_mention


def classify_sentiment(text: str) -> Tuple[Optional[str], float]:
    """Returns (sentiment_label, confidence_score). LLM-backed."""
    if not text or len(text.strip()) < 5:
        return None, 0.0
    result = classify_mention(text)
    return result["sentiment"], result["confidence"]