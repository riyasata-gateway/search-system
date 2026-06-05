"""Seed the 26 Datatopia workbook brands into the `brands` table.

This makes the workbook's *Top_Brands* tab the canonical brand catalog, so the
existing intelligence engines (BPI, momentum, SoV, launch readiness, …) and the
new `/api/v1/catalog/brands` endpoint operate on exactly these brands with their
category / owner / tier-signal / KPI-interest metadata.

Behaviour:
  • UPSERT by name — existing brands that share a name (Dafalgan, Nurofen,
    Voltaren, Imodium, Eucerin, Bepanthen, …) keep their `id`, so all existing
    mention entity-links and market-data rows stay intact.
  • New workbook brands are inserted.
  • Brand groups are created per owner so share-of-voice / competitor math has a
    parent grouping.
  • It is NON-destructive: pre-existing generic brands that are not in the
    workbook list are left in the table (they keep their historical mention
    links) but they no longer appear in the framework catalog — the catalog API
    is driven by core/framework_catalog.TOP_BRANDS, which contains only the 26.

It also regenerates data/pharma_dictionary/brands_be_fr.csv so a fresh
`seed_pharma_dictionary.py` run produces the 26-brand catalog.

Idempotent — safe to re-run.

Usage:  .venv/bin/python scripts/seed_brand_catalog.py
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from core.framework_catalog import TOP_BRANDS
from models.brand import Brand, BrandGroup

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "pharma_dictionary"
)
BRANDS_CSV = os.path.join(DATA_DIR, "brands_be_fr.csv")


def _group_name(owner: str) -> str:
    """Stable brand-group label from the owner string."""
    return owner.split(" / ")[0].split(" (")[0].strip() or owner


def upsert_brands(db: Session) -> dict[str, int]:
    brand_map: dict[str, int] = {}
    group_cache: dict[str, int] = {}

    for b in TOP_BRANDS:
        owner = b["owner"]
        gname = _group_name(owner)
        if gname not in group_cache:
            grp = db.execute(
                select(BrandGroup).where(BrandGroup.name == gname)
            ).scalar_one_or_none()
            if grp is None:
                grp = BrandGroup(name=gname, manufacturer=owner)
                db.add(grp)
                db.flush()
            group_cache[gname] = grp.id

        name = b["name"]
        brand = db.execute(select(Brand).where(Brand.name == name)).scalar_one_or_none()
        if brand is None:
            brand = Brand(name=name)
            db.add(brand)

        # Upsert metadata (preserve id if the row already existed).
        brand.manufacturer = owner
        brand.country = b.get("country") or None
        brand.category = b["category"]
        brand.tier_a_signal = b["tier_a_signal"]
        brand.tier_bc_signal = b["tier_bc_signal"]
        brand.kpi_roles = b["kpi_roles"]
        brand.brand_group_id = group_cache[gname]
        # These are our own (non-competitor) tracked brands by default.
        brand.is_competitor = False
        db.flush()
        brand_map[name] = brand.id

    db.commit()
    return brand_map


def regenerate_csv() -> None:
    """Rewrite brands_be_fr.csv to the 26-brand catalog (richer columns)."""
    fields = [
        "name", "manufacturer", "country", "is_competitor",
        "brand_group_name", "category", "kpi_roles",
    ]
    with open(BRANDS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for b in TOP_BRANDS:
            w.writerow({
                "name": b["name"],
                "manufacturer": b["owner"],
                "country": ",".join(b.get("country") or []),
                "is_competitor": "false",
                "brand_group_name": _group_name(b["owner"]),
                "category": b["category"],
                "kpi_roles": "|".join(b["kpi_roles"]),
            })


def main() -> None:
    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        brand_map = upsert_brands(db)
    regenerate_csv()
    print(f"  Brands upserted: {len(brand_map)}")
    print(f"  brands_be_fr.csv regenerated → {BRANDS_CSV}")


if __name__ == "__main__":
    main()