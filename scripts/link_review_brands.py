"""Link review mentions to framework brand entities by their `brand_name`.

Why: the 445k farmaline/medi-market reviews were imported with a `brand_name`
column (e.g. "La Roche-Posay", "Eucerin", "Vichy") but were never linked into
`mention_entities`. Every framework brand therefore had **zero** linked mentions,
so the DIA engines (Share of Voice, sentiment, momentum, review trend) and the
brand dashboards rendered empty — even though the data is sitting right there.

This connects each review to the framework brand it is about, matching the
review's `brand_name` against `brands.name` (case-insensitive) plus a small set
of name variants (workbook names carry suffixes the reviews don't, e.g.
"D-Cure (vitamin D)" → "D-Cure", "Bepanthol / Bepanthen" → both halves).

Deterministic, set-based, idempotent: a (mention, brand) pair already present in
`mention_entities` is skipped, so re-running only fills gaps.

Usage:  .venv/bin/python scripts/link_review_brands.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import defaultdict

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from core.config import settings
from models.brand import Brand
from models.mention import EntityType, Mention, MentionEntity

_REVIEW_SOURCES = ("farmaline", "medimarket")

# Extra aliases for workbook brand names that differ from the review brand_name.
_EXTRA_ALIASES = {
    "Bion3": ["Bion 3"],
}


def _candidates(name: str) -> list[str]:
    """All lower-cased strings a review brand_name might use for this brand."""
    cands = {name}
    if "/" in name:
        cands.update(p.strip() for p in name.split("/"))
    if "(" in name:
        cands.add(name.split("(")[0].strip())
    cands.update(_EXTRA_ALIASES.get(name, []))
    return sorted({c.lower() for c in cands if c})


def main():
    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        # Framework brands only (those carry the workbook `category`).
        brands = db.execute(
            select(Brand).where(Brand.category.isnot(None))
        ).scalars().all()

        # alias(lower) -> brand_id  (first writer wins; framework names are distinct)
        alias_to_brand: dict[str, int] = {}
        for b in brands:
            for alias in _candidates(b.name):
                alias_to_brand.setdefault(alias, b.id)

        # Existing links so we stay idempotent: brand_id -> set(mention_id).
        existing = defaultdict(set)
        for mid, bid in db.execute(
            select(MentionEntity.mention_id, MentionEntity.entity_id)
            .where(MentionEntity.entity_type == EntityType.brand)
        ).all():
            existing[bid].add(mid)

        # All review mentions that carry a brand_name.
        rows = db.execute(
            select(Mention.id, Mention.brand_name)
            .where(Mention.source_type.in_(_REVIEW_SOURCES))
            .where(Mention.brand_name.isnot(None))
            .where(Mention.is_deleted == False)  # noqa: E712
        ).all()

        made = 0
        per_brand = defaultdict(int)
        unmatched = defaultdict(int)
        for mid, bname in rows:
            bid = alias_to_brand.get((bname or "").strip().lower())
            if bid is None:
                unmatched[bname] += 1
                continue
            if mid in existing[bid]:
                continue
            db.add(MentionEntity(
                mention_id=mid,
                entity_type=EntityType.brand,
                entity_id=bid,
                confidence=1.0,
            ))
            existing[bid].add(mid)
            per_brand[bid] += 1
            made += 1
            if made % 5000 == 0:
                db.commit()
                print(f"  …{made} links written")
        db.commit()

        id_to_name = {b.id: b.name for b in brands}
        print(f"\nDone. Wrote {made} new brand links across "
              f"{sum(1 for v in per_brand.values() if v)} framework brands.")
        for bid, n in sorted(per_brand.items(), key=lambda x: -x[1]):
            print(f"  {id_to_name.get(bid, bid):35s} +{n}")

        total = dict(db.execute(
            select(MentionEntity.entity_type, func.count(MentionEntity.id))
            .group_by(MentionEntity.entity_type)
        ).all())
        print("\nmention_entities by type now:",
              {str(k): int(v) for k, v in total.items()})


if __name__ == "__main__":
    main()
