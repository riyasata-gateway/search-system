"""Unified NLP classifier — replaces XLM-RoBERTa + BART-MNLI with a single
OpenAI structured-output call per mention.

Returns sentiment + topic + intent + an adverse-event-context flag in one
shot. Replaces:
  - processing.sentiment.classify_sentiment       (XLM-RoBERTa, ~700MB)
  - processing.topic_classifier.classify_topic    (BART-MNLI, ~1.5GB)
  - processing.topic_classifier.classify_intent   (BART-MNLI again)

Kept separate (NOT replaced by LLM):
  - language_detection (lingua-py)  — too cheap to LLM-call
  - entity_resolution (dictionary)  — must be deterministic for pharma
  - risk_detector (regex)           — high-recall first pass for AE; LLM
                                       can OPTIONALLY verify positives via
                                       `verify_risk_with_llm()` below
  - embeddings (sentence-transformers) — Qdrant needs local vectors

Cost note: ~$0.00003 / mention with gpt-4o-mini → $9/month for 10K/day.
Failure-safe: returns neutral/general/other on any error — never raises.
"""
import asyncio
import json
from functools import lru_cache
from typing import Dict, List, Optional

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)


# ── Canonical label sets (must match models.mention.{Sentiment,Topic,Intent}) ─
_SENTIMENTS = {"positive", "neutral", "negative"}
_TOPICS = {
    "price", "efficacy", "side_effect", "availability",
    "packaging", "recommendation", "general",
}
_INTENTS = {
    "complaint", "question", "purchase_intent",
    "comparison", "recommendation", "other",
}

_SYSTEM_PROMPT = """You are a multilingual pharmaceutical mention classifier for PharmaWatch (EU pharma intelligence, Belgium + France).

Given a single mention text (in French / Dutch / German / English), return STRICT JSON with these keys:

{
  "sentiment": "positive | neutral | negative",
  "topic":     "price | efficacy | side_effect | availability | packaging | recommendation | general",
  "intent":    "complaint | question | purchase_intent | comparison | recommendation | other",
  "is_adverse_event_signal": true | false,
  "confidence": 0.0-1.0
}

Rules:
- `sentiment` is the OVERALL emotional tone of the writer toward the drug/brand.
- `topic` is what the mention is ABOUT. Pick the single best match.
- `intent` is what the WRITER is doing. Pick the single best match.
- `is_adverse_event_signal` = true ONLY if the text describes a personal/patient adverse reaction, side effect after taking the drug, allergic reaction, hospitalisation, or symptom-after-use. NEWS about adverse events in general is FALSE. Be conservative — false negatives are worse than false positives in pharmacovigilance.
- `confidence` is your own self-assessed certainty across the four labels above.

Reply with ONLY the JSON object. No prose, no markdown fence."""

def _safe_bool(parsed: Dict, key: str, default: bool) -> bool:
    v = parsed.get(key, default)
    return bool(v) if isinstance(v, bool) else default


# ── Brand-relevance disambiguation (batched) ─────────────────────────────────
# The authoritative namesake check: is a string-matched mention really about the
# pharma/cosmetic brand, or a namesake (town like Vichy/Avène, a person, a TV
# show, an unrelated company)? Done in BATCHES (many texts per call) and the
# caller runs batches in PARALLEL — far cheaper than one call per mention.
_BRAND_RELEVANCE_SYSTEM = """You are a pharmaceutical & dermocosmetic market analyst for PharmaWatch (Belgium + France).

You are given one BRAND (a pharma or dermocosmetic product/company) and a numbered list of short texts in which that brand NAME was string-matched. For each text decide whether it is genuinely about THAT brand — its product, range, company, availability, pricing, safety, marketing — versus a NAMESAKE: a town/place (e.g. Vichy, Avène, La Roche-Posay), a person/surname (e.g. a coach or politician), a TV show/film, a sports team, or an unrelated company (food, watches, chemicals, software).

Return STRICT JSON: {"results": [{"i": <number>, "relevant": true|false}, ...]} with one entry per input text. No prose."""


def classify_brand_relevance(brand: str, context: str, texts: List[str]) -> List[bool]:
    """Batch namesake check for ONE brand. Returns a bool per input text (aligned
    by order). On any error returns all-True (fail-open — the caller's cheap
    keyword gate has already run, so we never delete on an LLM failure).
    """
    if not texts:
        return []
    if not settings.OPENAI_API_KEY:
        logger.warning("brand_relevance_no_openai_key")
        return [True] * len(texts)

    ctx = f" ({context})" if context else ""
    numbered = "\n".join(f"{i+1}. {(t or '')[:300]}" for i, t in enumerate(texts))
    user = f"BRAND: {brand}{ctx}\n\nTEXTS:\n{numbered}"
    try:
        completion = _client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _BRAND_RELEVANCE_SYSTEM},
                {"role": "user", "content": user},
            ],
            max_completion_tokens=min(4000, 40 * len(texts) + 100),
            response_format={"type": "json_object"},
            temperature=0,
        )
        parsed = json.loads(completion.choices[0].message.content or "{}")
        results = {int(r["i"]): bool(r.get("relevant", True)) for r in parsed.get("results", [])}
        # Default missing indices to True (fail-open).
        return [results.get(i + 1, True) for i in range(len(texts))]
    except Exception as exc:
        logger.warning("brand_relevance_failed", brand=brand, error=str(exc))
        return [True] * len(texts)


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def _safe_label(value: str, allowed: set, default: str) -> str:
    if not value:
        return default
    v = value.strip().lower().replace(" ", "_")
    return v if v in allowed else default


def classify_mention(text: str, lang: Optional[str] = None) -> Dict:
    """Single-call classifier. Returns:
        {sentiment, topic, intent, is_adverse_event_signal, confidence, model}

    Falls back to safe neutrals on any error (logged at warning level).
    Synchronous so it slots into the existing sync Celery worker.
    """
    fallback = {
        "sentiment": "neutral",
        "topic": "general",
        "intent": "other",
        "is_adverse_event_signal": False,
        "confidence": 0.0,
        "model": settings.OPENAI_MODEL,
    }
    if not text or len(text.strip()) < 5:
        return fallback
    if not settings.OPENAI_API_KEY:
        logger.warning("llm_classifier_no_openai_key")
        return fallback

    try:
        completion = _client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": (text or "")[:2000]},
            ],
            max_completion_tokens=200,
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = completion.choices[0].message.content or "{}"
        parsed = json.loads(raw)
    except Exception as exc:
        logger.warning("llm_classifier_failed", error=str(exc))
        return fallback

    return {
        "sentiment": _safe_label(parsed.get("sentiment", ""), _SENTIMENTS, "neutral"),
        "topic": _safe_label(parsed.get("topic", ""), _TOPICS, "general"),
        "intent": _safe_label(parsed.get("intent", ""), _INTENTS, "other"),
        "is_adverse_event_signal": bool(parsed.get("is_adverse_event_signal", False)),
        "confidence": float(parsed.get("confidence", 0.0) or 0.0),
        "model": settings.OPENAI_MODEL,
    }


def verify_risk_with_llm(text: str, regex_flagged_type: str) -> Dict:
    """Second-pass false-positive reducer for the regex risk detector.

    The regex layer in `processing.risk_detector` has high recall by design
    (better to flag a non-AE than miss one). When it flags something, call
    this to ask the LLM whether the *context* genuinely supports the flag.

    Returns: {is_confirmed: bool, confidence: float, reason: str}.
    Never *removes* a flag from the worker pipeline — the human review queue
    still sees everything. The LLM verdict goes into MentionClassification's
    confidence_score so reviewers can triage faster.
    """
    fallback = {"is_confirmed": True, "confidence": 0.5,
                "reason": "llm_unavailable_kept_regex_flag"}
    if not settings.OPENAI_API_KEY or not text:
        return fallback
    prompt = (
        f"A regex flagged this text as a '{regex_flagged_type}' signal. "
        "Does the text genuinely describe this risk first-hand, or is it a "
        "news report / general knowledge / unrelated mention? "
        "Reply with JSON: {is_confirmed: bool, confidence: 0-1, reason: short string}."
    )
    try:
        completion = _client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text[:1500]},
            ],
            max_completion_tokens=120,
            response_format={"type": "json_object"},
            temperature=0,
        )
        parsed = json.loads(completion.choices[0].message.content or "{}")
        return {
            "is_confirmed": bool(parsed.get("is_confirmed", True)),
            "confidence": float(parsed.get("confidence", 0.5) or 0.5),
            "reason": (parsed.get("reason") or "")[:200],
        }
    except Exception as exc:
        logger.warning("llm_risk_verify_failed", error=str(exc))
        return fallback


def translate_to_english(text: str, src_lang: str) -> Optional[str]:
    """Drop-in replacement for processing.translation.translate_to_english.
    Uses OpenAI instead of Helsinki opus-mt — better for short consumer text."""
    if src_lang == "en" or not text or len(text.strip()) < 5:
        return text
    if not settings.OPENAI_API_KEY:
        return None
    try:
        completion = _client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system",
                 "content": ("Translate the user message into English. "
                             "Reply with ONLY the translation. "
                             "Preserve drug brand names verbatim.")},
                {"role": "user", "content": text[:2000]},
            ],
            max_completion_tokens=400,
            temperature=0,
        )
        return (completion.choices[0].message.content or "").strip() or None
    except Exception as exc:
        logger.warning("llm_translate_failed", error=str(exc), src_lang=src_lang)
        return None