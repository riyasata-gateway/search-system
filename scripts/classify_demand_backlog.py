"""Scoped classification backfill — classify the LINKED, unclassified
demand/opinion mentions (reviews / news / social) so the topic/sentiment/intent
KPIs and the corpus analytics (B9/B10/B11/B16) reflect them, and so B3's new
`reimbursement` intent populates.

Deliberately NOT the whole unclassified pool: evidence/reference rows (PubMed,
trials, BCFI, openFDA, Wikipedia) carry no consumer sentiment/intent, and
unlinked news is noise — classifying either would waste LLM calls. We scope to
mentions that are (a) linked to a brand and (b) from a demand/opinion source.

One LLM call per mention (sentiment + topic + intent + AE flag) + the cheap regex
risk pass. No embeddings (not needed for these analytics). Idempotent: only rows
with no existing classification are touched. Usage: .venv/bin/python scripts/classify_demand_backlog.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import Counter
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from core.config import settings
from core.source_taxonomy import DEMAND_SOURCE_TYPES
from models.mention import MentionClassification
from processing.llm_classifier import classify_mention
from processing.risk_detector import detect_risk
from processing.language_detection import detect_language


def main():
    eng = create_engine(settings.DATABASE_SYNC_URL)
    with Session(eng) as db:
        rows = db.execute(text("""
            SELECT DISTINCT m.id, coalesce(m.clean_text, m.raw_text) AS body, m.language
            FROM mentions m
            JOIN mention_entities me ON me.mention_id = m.id AND me.entity_type = 'brand'
            LEFT JOIN mention_classifications mc ON mc.mention_id = m.id
            WHERE mc.id IS NULL AND m.is_deleted = false
              AND m.source_type = ANY(:d)
        """), {"d": list(DEMAND_SOURCE_TYPES)}).fetchall()
        total = len(rows)
        print(f"classifying {total} linked, unclassified demand/opinion mentions…")

        intents = Counter()
        done = 0
        for mid, body, lang in rows:
            text_in = (body or "").strip()
            if len(text_in) < 5:
                continue
            lg = lang or detect_language(text_in) or "en"
            c = classify_mention(text_in, lang=lg)
            risk = detect_risk(text_in, lang=lg)
            db.add(MentionClassification(
                mention_id=mid,
                sentiment=c["sentiment"], topic=c["topic"], intent=c["intent"],
                risk_type=risk.risk_type,
                is_adverse_event_candidate=risk.is_adverse_event_candidate,
                is_prescription_promotion=risk.is_prescription_promotion,
                confidence_score=round(c["confidence"], 4), model_name=c["model"],
            ))
            intents[c["intent"]] += 1
            done += 1
            if done % 50 == 0:
                db.commit()
                print(f"  {done}/{total}  intents so far: {dict(intents)}")
        db.commit()
        print(f"DONE: classified {done} mentions. intent distribution: {dict(intents)}")
        print(f"  reimbursement (new B3 intent) hits: {intents.get('reimbursement', 0)}")


if __name__ == "__main__":
    main()
