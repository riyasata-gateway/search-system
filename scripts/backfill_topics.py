"""Back-fill `topic` on review classifications that have sentiment but no topic.

The rating-heuristic review classifier set sentiment from the star rating but left
`topic = NULL` on ~98% of reviews, so topic-resonance KPIs (Key Message Tuning,
topic clusters) had almost nothing to group by. This applies the same rule-based,
multilingual keyword topics used elsewhere (scripts/backfill_classifications._topic)
as fast set-based UPDATEs over review-source mentions, in priority order
(side_effect → price → efficacy → availability → recommendation → general).

Idempotent: only touches rows where topic IS NULL. Usage: .venv/bin/python scripts/backfill_topics.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import create_engine, text
from core.config import settings

REVIEW_SOURCES = ("farmaline", "medimarket")

# (topic, [keywords]) — ORDER MATTERS: side_effect before efficacy so "side effect"
# isn't captured by efficacy's "effect". 'general' is the catch-all for the rest.
RULES = [
    ("side_effect", ["side effect", "adverse", "reaction", "effet secondaire", "bijwerking",
                     "nebenwirkung", "nausea", "nausée", "pain", "douleur", "vertige", "pijn",
                     "schmerz", "rash", "allergi"]),
    ("price",       ["price", "cost", "cheap", "expensive", "prix", "coût", "prijs", "goedkoop", "preis"]),
    ("efficacy",    ["work", "effect", "relief", "helps", "efficac", "works", "wirkt", "werkt",
                     "fonctionne", "aide", "soulag"]),
    ("availability",["stock", "available", "find", "shortage", "rupture", "uitverkocht",
                     "ausverkauft", "indispo"]),
    ("recommendation",["recommend", "suggest", "recommande", "aanraden", "empfehlen"]),
]


def main():
    eng = create_engine(settings.DATABASE_SYNC_URL)
    total = 0
    with eng.begin() as conn:
        before = conn.execute(text("""
            SELECT count(*) FROM mention_classifications mc JOIN mentions m ON m.id=mc.mention_id
            WHERE mc.topic IS NULL AND m.source_type = ANY(:src)
        """), {"src": list(REVIEW_SOURCES)}).scalar()
        print(f"review classifications with topic NULL (before): {before}")
        for topic, kws in RULES:
            like = " OR ".join(f"lower(coalesce(m.clean_text,m.raw_text)) LIKE :kw{i}" for i in range(len(kws)))
            params = {f"kw{i}": f"%{k.lower()}%" for i, k in enumerate(kws)}
            params["src"] = list(REVIEW_SOURCES)
            params["topic"] = topic
            n = conn.execute(text(f"""
                UPDATE mention_classifications mc SET topic = :topic
                FROM mentions m
                WHERE m.id = mc.mention_id AND mc.topic IS NULL
                  AND m.source_type = ANY(:src) AND ({like})
            """), params).rowcount
            print(f"  → {topic}: {n}")
            total += n
        # Everything still NULL → general (the review had no topical keyword).
        n = conn.execute(text("""
            UPDATE mention_classifications mc SET topic = 'general'
            FROM mentions m
            WHERE m.id = mc.mention_id AND mc.topic IS NULL AND m.source_type = ANY(:src)
        """), {"src": list(REVIEW_SOURCES)}).rowcount
        print(f"  → general (rest): {n}")
        total += n
    print(f"backfilled topic on {total} review classifications.")


if __name__ == "__main__":
    main()