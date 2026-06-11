#!/usr/bin/env python
"""LLM-enrich the *non-positive* review subset with topic / intent / AE signal.

Per the agreed design, sentiment for all reviews is rating-derived (cheap,
deterministic). This script adds the richer NLP facets the pharmacist & marketing
lenses need — topic (side_effect / efficacy / price / …), intent, and the
adverse-event signal — but only where it pays off:

    * every review with rating <= 3 (complaints / lukewarm — the safety &
      detractor signal), plus
    * a bounded random sample of positives (--positive-sample) so "top positive
      themes" has data.

The rating-derived `sentiment` is preserved (we trust the star rating); only
topic / intent / is_adverse_event_candidate / risk_type are written, and
model_name is stamped with the OpenAI model so runs are resumable (already-
enriched rows are skipped).

Usage:
    python scripts/enrich_reviews_llm.py                      # negatives+neutrals + 3000 positives
    python scripts/enrich_reviews_llm.py --positive-sample 0  # only rating<=3
    python scripts/enrich_reviews_llm.py --workers 8 --limit 5000
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session

from core.config import settings
from models.mention import Mention, MentionClassification, RiskType, Topic, Intent
from processing.llm_classifier import classify_mention

REVIEW_SOURCES = ("farmaline", "medimarket")


def _select_targets(db, positive_sample: int, limit: int):
    """Return [(mention_id, clean_text, language)] needing enrichment."""
    enriched_model = settings.OPENAI_MODEL

    base = (
        select(Mention.id, Mention.clean_text, Mention.language)
        .join(MentionClassification, MentionClassification.mention_id == Mention.id)
        .where(
            Mention.source_type.in_(REVIEW_SOURCES),
            Mention.is_deleted.is_(False),
            Mention.clean_text.isnot(None),
            MentionClassification.model_name != enriched_model,
        )
    )
    non_positive = base.where(Mention.rating <= 3)
    rows = db.execute(non_positive).all()

    if positive_sample > 0:
        pos = (base.where(Mention.rating >= 4)
               .order_by(func.random())
               .limit(positive_sample))
        rows += db.execute(pos).all()

    if limit:
        rows = rows[:limit]
    return rows


def _classify_one(row):
    mid, text, lang = row
    res = classify_mention(text or "", lang)
    return mid, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--positive-sample", type=int, default=3000)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if not settings.OPENAI_API_KEY:
        print("WARNING: OPENAI_API_KEY not set — classify_mention returns neutral "
              "fallbacks. Topic/AE enrichment will be a no-op.", flush=True)

    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        targets = _select_targets(db, args.positive_sample, args.limit)
    print(f"[enrich] {len(targets):,} reviews to classify "
          f"(model={settings.OPENAI_MODEL}, workers={args.workers})", flush=True)
    if not targets:
        return

    valid_topics = {t.value for t in Topic}
    valid_intents = {i.value for i in Intent}

    done = 0
    buf = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(_classify_one, r) for r in targets]
        for fut in as_completed(futures):
            mid, res = fut.result()
            topic = res.get("topic") if res.get("topic") in valid_topics else "general"
            intent = res.get("intent") if res.get("intent") in valid_intents else "other"
            is_ae = bool(res.get("is_adverse_event_signal"))
            buf.append({
                "mention_id": mid,
                "topic": topic,
                "intent": intent,
                "is_ae": is_ae,
                "conf": round(float(res.get("confidence", 0.0) or 0.0), 3),
            })
            done += 1
            if len(buf) >= 200:
                _flush(engine, buf)
                buf = []
                print(f"[enrich] {done:,}/{len(targets):,}", flush=True)
    if buf:
        _flush(engine, buf)
    print(f"[enrich] DONE — {done:,} reviews enriched", flush=True)


def _flush(engine, buf):
    with Session(engine) as db:
        for b in buf:
            values = {
                "topic": b["topic"],
                "intent": b["intent"],
                "is_adverse_event_candidate": b["is_ae"],
                "confidence_score": b["conf"],
                "model_name": settings.OPENAI_MODEL,
            }
            if b["is_ae"]:
                values["risk_type"] = RiskType.adverse_event.value
            db.execute(
                update(MentionClassification)
                .where(MentionClassification.mention_id == b["mention_id"])
                .values(**values)
            )
        db.commit()


if __name__ == "__main__":
    main()
