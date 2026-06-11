"""Import the Belgian supplier categorisation workbook into the `brands` table.

Source: belgian_supplier_primary_category_v2_80pct_high.xlsx (sheet
"Categorised_Brands") — ~2016 Belgian pharmacy suppliers, each assigned ONE
primary category (NUT/RX/PAC/PEC/OTC) with a confidence + rationale.

What it does:
  • UPSERT every supplier by name (case-insensitive). Existing rows keep their id
    (so any links survive); new suppliers are inserted with country=['BE'].
  • Writes primary_category / category_confidence / category_rationale.
  • Leaves the fine-grained `category` (competitive family) ALONE — suppliers get
    no `category`, so they don't pollute peer-set / share-of-voice math and don't
    leak into the framework brand pickers (which filter on category IS NOT NULL).
  • Backfills primary_category for the existing framework *product* brands by
    mapping their fine-grained category → the 5-code taxonomy, so they're
    filterable in the Brand Catalog too.

Honest by design: this only classifies + registers brands. KPIs are computed
on-demand from ingested data (reviews/SAM/Farmaline/…); a supplier with no
product-level data correctly renders "Insufficient data"/"Connect feed".

Idempotent — safe to re-run.

Usage:  .venv/bin/python scripts/import_supplier_catalog.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from core.config import settings
from core.framework_catalog import PRIMARY_CATEGORY_CODES
from models.brand import Brand

WORKBOOK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "belgian_supplier_primary_category_v2_80pct_high.xlsx",
)
SHEET = "Categorised_Brands"

# Map the framework product brands' fine-grained `category` → 5-code taxonomy so
# the existing 31 brands are filterable alongside the imported suppliers.
# (Substring match, first hit wins; checked in order.)
_FAMILY_TO_CODE = [
    ("rx specialty", "RX"),
    ("infant nutrition", "NUT"),
    ("supplement", "NUT"),
    ("phyto", "NUT"),
    ("aromatherapy", "NUT"),
    ("baby care", "OTC"),
    ("dermocosmetic", "OTC"),
    ("wound care", "OTC"),
    ("skin", "OTC"),
    ("otc", "OTC"),
]


def _family_to_code(category: str | None) -> str | None:
    if not category:
        return None
    c = category.lower()
    for needle, code in _FAMILY_TO_CODE:
        if needle in c:
            return code
    return "OTC"  # default for any remaining consumer family


def import_suppliers(db: Session) -> dict:
    df = pd.read_excel(WORKBOOK, sheet_name=SHEET)
    df = df.dropna(subset=["Supplier / Brand", "Primary Category"])

    # Existing brands keyed by lower(name) for case-insensitive upsert.
    existing = {b.name.lower(): b for b in db.execute(select(Brand)).scalars().all()}

    inserted = updated = skipped = 0
    for _, row in df.iterrows():
        name = str(row["Supplier / Brand"]).strip()
        code = str(row["Primary Category"]).strip().upper()
        if not name or code not in PRIMARY_CATEGORY_CODES:
            skipped += 1
            continue
        conf = str(row.get("Confidence") or "").strip() or None
        rationale = str(row.get("Rationale") or "").strip() or None

        b = existing.get(name.lower())
        if b is None:
            b = Brand(name=name, country=["BE"], is_competitor=False)
            db.add(b)
            existing[name.lower()] = b
            inserted += 1
        else:
            updated += 1
        b.primary_category = code
        b.category_confidence = conf
        b.category_rationale = rationale

    # Backfill primary_category on framework product brands that the workbook
    # didn't cover (they're product brands, not suppliers).
    backfilled = 0
    for b in db.execute(select(Brand).where(Brand.primary_category.is_(None))).scalars().all():
        code = _family_to_code(b.category)
        if code:
            b.primary_category = code
            if not b.category_rationale:
                b.category_rationale = f"mapped from competitive family '{b.category}'"
            backfilled += 1

    db.commit()
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "backfilled": backfilled}


def main() -> None:
    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        stats = import_suppliers(db)
        total = db.execute(select(func.count()).select_from(Brand)).scalar_one()
        by_cat = dict(
            db.execute(
                select(Brand.primary_category, func.count())
                .group_by(Brand.primary_category)
                .order_by(Brand.primary_category)
            ).all()
        )
    print(f"Import complete: {stats}")
    print(f"Total brands now: {total}")
    print(f"By primary_category: {by_cat}")


if __name__ == "__main__":
    main()