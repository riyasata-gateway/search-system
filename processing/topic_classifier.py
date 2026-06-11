"""Backwards-compat shim — topic + intent are now classified by the unified
LLM classifier (processing.llm_classifier). For new code, call
`processing.llm_classifier.classify_mention(text)` directly to get sentiment +
topic + intent + AE flag in ONE OpenAI call (instead of three).
"""
from typing import Optional, Tuple

from processing.llm_classifier import classify_mention


def classify_topic(text: str) -> Tuple[Optional[str], float]:
    if not text or len(text.strip()) < 10:
        return "general", 0.5
    result = classify_mention(text)
    return result["topic"], result["confidence"]


def classify_intent(text: str) -> Tuple[Optional[str], float]:
    if not text or len(text.strip()) < 10:
        return "other", 0.5
    result = classify_mention(text)
    return result["intent"], result["confidence"]