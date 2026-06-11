"""Backfill `mention_entities` by running the deterministic dictionary entity
resolver over the existing mention corpus.

Why: the DIA intelligence layer (Brand Potential Index, Share of Voice, Momentum,
Market-Fit) all join `mentions → mention_entities → brands/products`. The corpus
was imported without the NLP worker's entity-resolution step, so
`mention_entities` is empty and every framework metric degrades to a neutral 0.5.
This links each mention to the brands/products it names.

Deterministic (substring match against brand names + product aliases — no LLM,
no embeddings). Idempotent: only mentions with zero entity rows are processed.

Usage:  python scripts/backfill_entities.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from core.config import settings
from models.mention import EntityType, Mention, MentionEntity
from processing.entity_resolution import get_dictionary


def main():
    resolver = get_dictionary()
    if not getattr(resolver, "_loaded", False):
        resolver.load(settings.DATABASE_SYNC_URL)

    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        # mentions that have no entity rows yet
        already = set(
            r[0] for r in db.execute(select(MentionEntity.mention_id).distinct()).all()
        )
        rows = db.execute(
            select(Mention.id, Mention.clean_text, Mention.raw_text,
                   Mention.language, Mention.country)
            .where(Mention.is_deleted == False)  # noqa: E712
        ).all()
        todo = [(mid, (clean or raw or ""), lang, country)
                for mid, clean, raw, lang, country in rows if mid not in already]

        print(f"Mentions: {len(rows)} | already linked: {len(already)} | to process: {len(todo)}")
        if not todo:
            print("Nothing to do.")
            return

        made = 0
        linked_mentions = 0
        for i, (mid, text, lang, country) in enumerate(todo, start=1):
            ents = resolver.resolve_entities(text, lang=lang or "en", country=country)
            seen = set()
            any_link = False
            for e in ents:
                key = (e["entity_type"], e["entity_id"])
                if key in seen:
                    continue
                seen.add(key)
                db.add(MentionEntity(
                    mention_id=mid,
                    entity_type=EntityType(e["entity_type"]),
                    entity_id=int(e["entity_id"]),
                    confidence=round(float(e.get("confidence", 1.0)), 3),
                ))
                made += 1
                any_link = True
            if any_link:
                linked_mentions += 1
            if i % 500 == 0:
                db.commit()
                print(f"  …{i}/{len(todo)}")
        db.commit()

        by_type = dict(db.execute(
            select(MentionEntity.entity_type, func.count(MentionEntity.id))
            .group_by(MentionEntity.entity_type)
        ).all())
        print(f"Done. Wrote {made} entity links across {linked_mentions} mentions "
              f"({len(todo) - linked_mentions} matched nothing).")
        print("By type:", {str(k): int(v) for k, v in by_type.items()})


if __name__ == "__main__":
    main()
