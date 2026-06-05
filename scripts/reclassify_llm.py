"""Re-classify mentions with the LLM, replacing the fast rule-based backfill.

`scripts/backfill_classifications.py` wrote quick keyword-based classifications
(tagged `model_name='rule_backfill'`) so semantic search had *something*. This
script upgrades them to a full LLM classification.

Classification is **LLM for everything**: a single structured call assigns
sentiment, topic, intent, risk_type (across all five categories) and the
prescription-promotion flag. The regex `detect_risk` is used **only as a
fallback** when the LLM call fails after retries — so a transient rate-limit
never silently loses the risk signal, but healthy rows are 100% LLM-driven.

Mirrors the data model of `workers/processing_worker.process_pending_mentions`
but updates the existing `mention_classifications` rows IN PLACE and re-stamps
`model_name` to the model used (idempotent: only `rule_backfill` rows are
targeted by default; failed rows keep `rule_backfill` so a re-run retries them).

Design: LLM calls run in a thread pool (I/O-bound); DB writes happen on the main
thread (SQLAlchemy Session is not thread-safe).

Does NOT auto-create AdverseEventCandidate rows / alerts for the historical
corpus (that would flood the review queue) — it only updates the classification +
risk flags that power semantic results, the role topic-tier and analytics.

Usage:
  python scripts/reclassify_llm.py                 # only rule_backfill rows
  python scripts/reclassify_llm.py --all
  python scripts/reclassify_llm.py --workers 16 --limit 500
"""
import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from models.mention import (
    Mention, MentionClassification, Sentiment, Topic, Intent, RiskType,
)
from processing.llm_classifier import _client, _safe_label, _SENTIMENTS, _TOPICS, _INTENTS
from processing.risk_detector import detect_risk

_RISK_TYPES = {"adverse_event", "shortage", "misinformation", "counterfeit", "none"}

# Extended prompt — the canonical classifier only emits an AE boolean, so we ask
# for the full risk_type here to make risk 100% LLM-driven.
_SYSTEM_PROMPT = """You are a multilingual pharmaceutical mention classifier for PharmaWatch (EU pharma intelligence, Belgium + France).

Given a single mention text (French / Dutch / German / English), return STRICT JSON:

{
  "sentiment": "positive | neutral | negative",
  "topic":     "price | efficacy | side_effect | availability | packaging | recommendation | general",
  "intent":    "complaint | question | purchase_intent | comparison | recommendation | other",
  "risk_type": "adverse_event | shortage | misinformation | counterfeit | none",
  "is_prescription_promotion": true | false,
  "confidence": 0.0-1.0
}

Rules:
- `sentiment` = overall emotional tone of the writer toward the drug/brand.
- `topic` = what the mention is ABOUT (single best match).
- `intent` = what the WRITER is doing (single best match).
- `risk_type`: pick the single most serious applicable signal.
  - "adverse_event": a personal/patient adverse reaction, side effect after taking the drug, allergic reaction, hospitalisation, or symptom-after-use. Be conservative — in pharmacovigilance a false negative is worse than a false positive.
  - "shortage": the medicine is unavailable / out of stock / supply rupture.
  - "misinformation": a false or misleading medical/pharmaceutical claim.
  - "counterfeit": falsified, fake, or illegally sourced medicine.
  - "none": none of the above.
- `is_prescription_promotion` = true ONLY if the text promotes a prescription-only medicine to the general public (restricted in the EU).
- `confidence` = your self-assessed certainty across all labels.

Reply with ONLY the JSON object. No prose, no markdown fence."""


def _classify_with_retry(text: str, retries: int = 4) -> dict:
    """LLM classify with exponential backoff. Returns {ok: False} after all
    retries so the caller can fall back to regex rather than overwrite junk."""
    if not text or len(text.strip()) < 5:
        return {"ok": False, "reason": "too_short"}
    last = None
    for attempt in range(retries):
        try:
            completion = _client().chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text[:2000]},
                ],
                max_completion_tokens=220,
                response_format={"type": "json_object"},
                temperature=0,
            )
            parsed = json.loads(completion.choices[0].message.content or "{}")
            return {
                "ok": True,
                "sentiment": _safe_label(parsed.get("sentiment", ""), _SENTIMENTS, "neutral"),
                "topic": _safe_label(parsed.get("topic", ""), _TOPICS, "general"),
                "intent": _safe_label(parsed.get("intent", ""), _INTENTS, "other"),
                "risk_type": _safe_label(parsed.get("risk_type", ""), _RISK_TYPES, "none"),
                "is_promo": bool(parsed.get("is_prescription_promotion", False)),
                "confidence": float(parsed.get("confidence", 0.0) or 0.0),
            }
        except Exception as exc:  # rate limit, transient network, parse error
            last = exc
            time.sleep((2 ** attempt) + random.random())
    return {"ok": False, "reason": str(last)[:200]}


def _work(item: tuple) -> dict:
    """Thread worker: API/CPU only, NO DB. item = (mention_id, text, lang)."""
    mid, text, lang = item
    res = _classify_with_retry(text)
    if res.get("ok"):
        return {"mid": mid, **res, "is_ae": res["risk_type"] == "adverse_event"}
    # Fallback: regex risk only; sentiment/topic/intent left to the caller (kept).
    risk = detect_risk(text or "", lang=lang or "en")
    return {"mid": mid, "ok": False, "reason": res.get("reason"),
            "risk_type": risk.risk_type, "is_ae": risk.is_adverse_event_candidate,
            "is_promo": risk.is_prescription_promotion}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="re-classify every live mention")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int, default=0, help="cap mentions processed (0 = no cap)")
    args = ap.parse_args()

    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        q = (
            select(MentionClassification.mention_id, Mention.clean_text,
                   Mention.raw_text, Mention.language)
            .join(Mention, Mention.id == MentionClassification.mention_id)
            .where(Mention.is_deleted == False)  # noqa: E712
        )
        if not args.all:
            q = q.where(MentionClassification.model_name == "rule_backfill")
        if args.limit:
            q = q.limit(args.limit)
        rows = db.execute(q).all()

    items = [(mid, (clean or raw or ""), lang) for mid, clean, raw, lang in rows]
    total = len(items)
    print(f"Mentions to re-classify with {settings.OPENAI_MODEL}: {total} "
          f"(workers={args.workers})", flush=True)
    if total == 0:
        print("Nothing to do.", flush=True)
        return

    results = []
    done = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_work, it): it[0] for it in items}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            done += 1
            if not r.get("ok"):
                failed += 1
            if done % 100 == 0 or done == total:
                print(f"  …{done}/{total} (api_failures={failed})", flush=True)

    # DB writes on the main thread, batched.
    with Session(engine) as db:
        by_id = {
            mc.mention_id: mc
            for mc in db.execute(
                select(MentionClassification).where(
                    MentionClassification.mention_id.in_([r["mid"] for r in results])
                )
            ).scalars().all()
        }
        updated = 0
        for r in results:
            mc = by_id.get(r["mid"])
            if mc is None:
                continue
            mc.risk_type = RiskType(r["risk_type"])
            mc.is_adverse_event_candidate = r["is_ae"]
            mc.is_prescription_promotion = r["is_promo"]
            if r.get("ok"):
                mc.sentiment = Sentiment(r["sentiment"])
                mc.topic = Topic(r["topic"])
                mc.intent = Intent(r["intent"])
                mc.confidence_score = round(min(0.999, r["confidence"]), 3)
                mc.model_name = settings.OPENAI_MODEL
            # failed rows keep their rule_backfill labels + model_name so a re-run
            # retries just them.
            updated += 1
            if updated % 500 == 0:
                db.commit()
        db.commit()

    ok = total - failed
    print(f"Done. LLM-classified {ok}/{total} rows (model='{settings.OPENAI_MODEL}'); "
          f"{failed} kept rule_backfill (API failures — re-run to retry).", flush=True)


if __name__ == "__main__":
    main()
