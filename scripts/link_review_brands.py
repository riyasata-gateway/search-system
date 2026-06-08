"""Link review mentions to brand entities by their `brand_name`.

Why: the 445k farmaline/medi-market reviews were imported with a `brand_name`
column (e.g. "La Roche-Posay", "Eucerin", "Vichy") but were never linked into
`mention_entities`. A brand therefore has **zero** linked mentions, so the DIA
engines (Share of Voice, sentiment, momentum, review trend) and the brand
dashboards render empty — even though the data is sitting right there.

This connects each review to the brand it is about, matching the review's
`brand_name` against `brands.name`. Matching is done on a *normalised* key
(lower-cased, parentheticals dropped, punctuation collapsed to single spaces) so
that workbook/catalogue spelling differences line up — e.g.
"D-Cure (vitamin D)" ↔ "D-Cure", "PHARMA-PACK" ↔ "Pharma Pack",
"Bion3" ↔ "Bion 3". Slash- and parenthesis-composite workbook names
("Bepanthol / Bepanthen") fan out to each half.

Originally this only linked the 31 framework brands (those carrying the workbook
`category`). It now links **every** brand in the catalogue so the newly-imported
supplier brands get their review-derived KPIs too. On the rare normalised-name
collision (two brands sharing a key) the framework brand wins, otherwise the
lowest id — and the collision is reported.

Deterministic, set-based, idempotent: a (mention, brand) pair already present in
`mention_entities` is skipped, so re-running only fills gaps.

Usage:  .venv/bin/python scripts/link_review_brands.py [--framework-only]
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import defaultdict

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from core.config import settings
from models.brand import Brand
from models.mention import EntityType, Mention, MentionEntity

_REVIEW_SOURCES = ("farmaline", "medimarket")

# Extra aliases for brand names that differ from the review brand_name beyond
# what normalisation already collapses.
_EXTRA_ALIASES = {
    "Bion3": ["Bion 3"],
}


def _normalise(s: str) -> str:
    """Match key: lower-cased, parentheticals dropped, punctuation → space.

    "D-Cure (vitamin D)" -> "d cure"; "PHARMA-PACK" -> "pharma pack".
    """
    s = (s or "").lower().strip()
    s = re.sub(r"\(.*?\)", " ", s)        # drop parentheticals
    s = re.sub(r"[^a-z0-9]+", " ", s)     # non-alphanumerics → space
    return " ".join(s.split())


def _candidates(name: str) -> list[str]:
    """All normalised strings a review brand_name might use for this brand."""
    cands = {name}
    if "/" in name:
        cands.update(p.strip() for p in name.split("/"))
    if "(" in name:
        cands.add(name.split("(")[0].strip())
    cands.update(_EXTRA_ALIASES.get(name, []))
    return sorted({_normalise(c) for c in cands if _normalise(c)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--framework-only", action="store_true",
                    help="restrict to the 31 workbook brands (legacy behaviour)")
    args = ap.parse_args()

    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        q = select(Brand)
        if args.framework_only:
            q = q.where(Brand.category.isnot(None))
        brands = db.execute(q).scalars().all()

        # normalised alias -> brand_id. On collision prefer the framework brand
        # (category set), otherwise the lowest id; report what we dropped.
        alias_to_brand: dict[str, int] = {}
        collisions: list[tuple[str, str, str]] = []
        by_id = {b.id: b for b in brands}
        for b in sorted(brands, key=lambda x: x.id):
            for alias in _candidates(b.name):
                cur = alias_to_brand.get(alias)
                if cur is None:
                    alias_to_brand[alias] = b.id
                    continue
                cur_brand = by_id[cur]
                # framework brand wins over a plain supplier brand
                if cur_brand.category is None and b.category is not None:
                    collisions.append((alias, cur_brand.name, b.name))
                    alias_to_brand[alias] = b.id
                else:
                    collisions.append((alias, b.name, cur_brand.name))

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
            bid = alias_to_brand.get(_normalise(bname))
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
              f"{sum(1 for v in per_brand.values() if v)} brands.")
        for bid, n in sorted(per_brand.items(), key=lambda x: -x[1])[:40]:
            print(f"  {id_to_name.get(bid, bid):35s} +{n}")

        if collisions:
            print(f"\n{len(collisions)} normalised-name collision(s) (kept → dropped):")
            for alias, kept, dropped in collisions:
                print(f"  {alias!r}: kept {kept!r}, dropped {dropped!r}")

        # Unmatched review brand_names with the biggest corpora — candidates for
        # an alias entry or a catalogue addition.
        top_unmatched = sorted(unmatched.items(), key=lambda x: -x[1])[:15]
        if top_unmatched:
            print("\nTop unmatched review brand_names (not in catalogue):")
            for name, n in top_unmatched:
                print(f"  {str(name):35s} {n}")

        total = dict(db.execute(
            select(MentionEntity.entity_type, func.count(MentionEntity.id))
            .group_by(MentionEntity.entity_type)
        ).all())
        print("\nmention_entities by type now:",
              {str(k): int(v) for k, v in total.items()})


if __name__ == "__main__":
    main()