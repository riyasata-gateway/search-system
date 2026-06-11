"""Permanently remove the legacy seeded brands (and their dependent rows).

The pre-framework demo seed left 14 brands with no `category` (Advil, Doliprane,
Zyrtec, …). They carry no framework metadata and no real linked data, and now
that every picker is framework-scoped they're dead weight. This deletes them and
everything that hangs off them, FK-safe, in a single transaction.

Run:  .venv/bin/python scripts/delete_seeded_brands.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

from core.config import settings


def main():
    engine = create_engine(settings.DATABASE_SYNC_URL)
    with engine.begin() as c:  # single transaction
        seeded = [r[0] for r in c.execute(text("select id from brands where category is null"))]
        if not seeded:
            print("No seeded brands to remove.")
            return
        prods = [r[0] for r in c.execute(
            text("select id from products where brand_id = any(:b)"), {"b": seeded})]
        print(f"Deleting {len(seeded)} brands and {len(prods)} of their products …")

        def run(sql, **p):
            res = c.execute(text(sql), p)
            return res.rowcount

        report = {}
        # product-children
        if prods:
            for tbl in ["adverse_event_candidates", "competitor_group_products",
                        "pharmacy_inventory", "pharmacy_sales", "product_aliases",
                        "recommendations"]:
                report[tbl] = run(f"delete from {tbl} where product_id = any(:p)", p=prods)
        # tables keyed by brand and/or product
        report["market_data"] = run(
            "delete from market_data where brand_id = any(:b) or product_id = any(:p)",
            b=seeded, p=prods or [-1])
        report["prescription_events"] = run(
            "delete from prescription_events where brand_id = any(:b) or product_id = any(:p)",
            b=seeded, p=prods or [-1])
        # brand-children
        report["search_topic_competitors"] = run(
            "delete from search_topic_competitors where brand_id = any(:b)", b=seeded)
        report["search_topics"] = run(
            "delete from search_topics where brand_id = any(:b)", b=seeded)
        # polymorphic mention links (no FK) for these brands + their products
        report["mention_entities(brand)"] = run(
            "delete from mention_entities where entity_type='brand' and entity_id = any(:b)", b=seeded)
        if prods:
            report["mention_entities(product)"] = run(
                "delete from mention_entities where entity_type='product' and entity_id = any(:p)", p=prods)
        # products, then brands
        report["products"] = run("delete from products where id = any(:p)", p=prods or [-1])
        report["brands"] = run("delete from brands where id = any(:b)", b=seeded)
        # brand_groups now orphaned
        report["brand_groups(orphaned)"] = run(
            "delete from brand_groups bg where not exists (select 1 from brands b where b.brand_group_id = bg.id)")

        print("Deleted rows:")
        for k, v in report.items():
            print(f"  {k:34s} {v}")
        print(f"\nRemaining brands: {c.execute(text('select count(*) from brands')).scalar()}")


if __name__ == "__main__":
    main()
