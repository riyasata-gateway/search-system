"""Backfill `mention_classifications` for mentions that were ingested before the
NLP worker ran (so semantic search and the role lens' topic tier have data).

Context
-------
Classifications are normally written by `workers/processing_worker.py`
(LLM-based: sentiment + topic + intent, plus the regex risk detector). When
mentions are imported without that worker, `mention_classifications` is empty,
so `/search/semantic` returns hits with `topic=None`/`sentiment=None` and the
topic half of the role lens is inert.

This script writes a FAST, DETERMINISTIC, rule-based classification — the same
lightweight keyword logic Live Search already uses for real-time results — plus
the real regex risk detector (`processing/risk_detector.detect_risk`). It is a
pragmatic backfill, not a replacement for the LLM pipeline: rows are tagged
`model_name='rule_backfill'` so the LLM worker can re-classify them later for
higher accuracy.

Idempotent: only mentions with NO classification row are processed.

Usage:  python scripts/backfill_classifications.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from models.mention import (
    Mention, MentionClassification, Sentiment, Topic, Intent, RiskType,
)
from processing.risk_detector import detect_risk

# ── lightweight keyword rules (mirror api/routers/live_search.py) ───────────────
_POS = ["great", "excellent", "helped", "works", "effective", "recommend", "relief",
        "better", "good", "perfect", "love", "amazing", "best", "safe",
        "efficace", "bien", "soulagé", "recommande", "super", "bon", "meilleur",
        "uitstekend", "helpt", "goed", "effectief", "prima", "werkt", "beste",
        "ausgezeichnet", "hilft", "wirksam", "empfehlen", "wirkt", "toll"]
_NEG = ["side effect", "adverse", "pain", "dizzy", "nausea", "vomit", "hospital",
        "dangerous", "overdose", "rash", "allergy", "worse", "bad", "terrible",
        "effet secondaire", "douleur", "vertige", "nausée", "dangereux", "pire",
        "bijwerking", "pijn", "duizelig", "misselijk", "gevaarlijk", "erger",
        "nebenwirkung", "schmerz", "schwindel", "übelkeit", "gefährlich"]


def _sentiment(text: str) -> Sentiment:
    tl = text.lower()
    neg = sum(1 for w in _NEG if w in tl)
    pos = sum(1 for w in _POS if w in tl)
    if neg > pos:
        return Sentiment.negative
    if pos > neg:
        return Sentiment.positive
    return Sentiment.neutral


def _topic(text: str) -> Topic:
    tl = text.lower()
    if any(w in tl for w in ["side effect", "adverse", "reaction", "effet secondaire",
                             "bijwerking", "nebenwirkung", "nausea", "pain", "douleur",
                             "vertige", "pijn", "schmerz", "rash", "allergi"]):
        return Topic.side_effect
    if any(w in tl for w in ["price", "cost", "cheap", "expensive", "prix", "coût",
                             "prijs", "goedkoop", "preis"]):
        return Topic.price
    if any(w in tl for w in ["work", "effect", "relief", "helps", "efficac", "works",
                             "wirkt", "werkt", "fonctionne", "aide"]):
        return Topic.efficacy
    if any(w in tl for w in ["stock", "available", "find", "shortage", "rupture",
                             "uitverkocht", "ausverkauft", "indispo"]):
        return Topic.availability
    if any(w in tl for w in ["recommend", "suggest", "try", "recommande", "aanraden",
                             "empfehlen"]):
        return Topic.recommendation
    return Topic.general


def main():
    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        # Mentions with no classification row yet.
        rows = db.execute(
            select(Mention.id, Mention.clean_text, Mention.raw_text, Mention.language)
            .outerjoin(MentionClassification,
                       MentionClassification.mention_id == Mention.id)
            .where(MentionClassification.id.is_(None), Mention.is_deleted == False)  # noqa: E712
        ).all()

        total = len(rows)
        print(f"Mentions to classify: {total}")
        if total == 0:
            print("Nothing to do — every live mention already has a classification.")
            return

        made = 0
        for mid, clean, raw, lang in rows:
            text = (clean or raw or "").strip()
            if not text:
                continue
            risk = detect_risk(text, lang=lang or "en")
            db.add(MentionClassification(
                mention_id=mid,
                sentiment=_sentiment(text),
                topic=_topic(text),
                intent=Intent.other,
                risk_type=RiskType(risk.risk_type),
                is_adverse_event_candidate=risk.is_adverse_event_candidate,
                is_prescription_promotion=risk.is_prescription_promotion,
                confidence_score=0.5,           # rule-based → modest confidence
                model_name="rule_backfill",
            ))
            made += 1
            if made % 500 == 0:
                db.commit()
                print(f"  …{made}/{total}")
        db.commit()
        print(f"Done. Wrote {made} classification rows (model_name='rule_backfill').")


if __name__ == "__main__":
    main()
