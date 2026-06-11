"""
Seed script: loads pharma dictionary CSVs into the PostgreSQL database.

Run once after `alembic upgrade head`:
    python scripts/seed_pharma_dictionary.py

Idempotent: skips rows that already exist by name/slug.
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from models.brand import Brand, BrandGroup
from models.product import Product, ProductAlias, ProductCategory

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "pharma_dictionary")

BRANDS_CSV = os.path.join(DATA_DIR, "brands_be_fr.csv")
PRODUCTS_CSV = os.path.join(DATA_DIR, "products_be_fr.csv")
ALIASES_CSV = os.path.join(DATA_DIR, "aliases_be_fr.csv")

CATEGORY_DISPLAY_NAMES = {
    "pain_relief": "Pain Relief",
    "digestive": "Digestive Health",
    "allergy": "Allergy & Hay Fever",
    "vitamins_supplements": "Vitamins & Supplements",
    "dermatology_otc": "Dermatology OTC",
}


def seed_categories(db: Session) -> dict[str, int]:
    category_map: dict[str, int] = {}
    for slug, display_name in CATEGORY_DISPLAY_NAMES.items():
        existing = db.execute(select(ProductCategory).where(ProductCategory.slug == slug)).scalar_one_or_none()
        if existing:
            category_map[slug] = existing.id
        else:
            cat = ProductCategory(slug=slug, name_en=display_name)
            db.add(cat)
            db.flush()
            category_map[slug] = cat.id
    db.commit()
    print(f"  Categories seeded: {len(category_map)}")
    return category_map


def seed_brands(db: Session) -> dict[str, int]:
    brand_map: dict[str, int] = {}
    brand_group_cache: dict[str, int] = {}

    with open(BRANDS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            group_name = row.get("brand_group_name", "").strip()
            if group_name and group_name not in brand_group_cache:
                existing_group = db.execute(
                    select(BrandGroup).where(BrandGroup.name == group_name)
                ).scalar_one_or_none()
                if existing_group:
                    brand_group_cache[group_name] = existing_group.id
                else:
                    grp = BrandGroup(name=group_name)
                    db.add(grp)
                    db.flush()
                    brand_group_cache[group_name] = grp.id

            name = row["name"].strip()
            existing = db.execute(select(Brand).where(Brand.name == name)).scalar_one_or_none()
            if existing:
                brand_map[name] = existing.id
                continue

            countries = [c.strip() for c in row.get("country", "").split(",") if c.strip()]
            brand = Brand(
                name=name,
                manufacturer=row.get("manufacturer", "").strip() or None,
                country=countries or None,
                is_competitor=row.get("is_competitor", "false").strip().lower() == "true",
                brand_group_id=brand_group_cache.get(group_name),
            )
            db.add(brand)
            db.flush()
            brand_map[name] = brand.id

    db.commit()
    print(f"  Brands seeded: {len(brand_map)}")
    return brand_map


def seed_products(db: Session, brand_map: dict[str, int], category_map: dict[str, int]) -> dict[str, int]:
    product_map: dict[str, int] = {}

    with open(PRODUCTS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row["name"].strip()
            existing = db.execute(select(Product).where(Product.name == name)).scalar_one_or_none()
            if existing:
                product_map[name] = existing.id
                continue

            brand_name = row.get("brand_name", "").strip()
            category_slug = row.get("category_slug", "").strip()
            countries = [c.strip() for c in row.get("country", "").split(",") if c.strip()]

            product = Product(
                name=name,
                brand_id=brand_map.get(brand_name),
                category_id=category_map.get(category_slug),
                active_ingredient=row.get("active_ingredient", "").strip() or None,
                cnk=row.get("cnk", "").strip() or None,
                ean=row.get("ean", "").strip() or None,
                is_otc=row.get("is_otc", "true").strip().lower() == "true",
                is_prescription=row.get("is_prescription", "false").strip().lower() == "true",
                country=countries or None,
            )
            db.add(product)
            db.flush()
            product_map[name] = product.id

    db.commit()
    print(f"  Products seeded: {len(product_map)}")
    return product_map


def seed_aliases(db: Session, product_map: dict[str, int]) -> int:
    count = 0
    with open(ALIASES_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            product_name = row["product_name"].strip()
            product_id = product_map.get(product_name)
            if not product_id:
                print(f"  WARNING: Product not found for alias row: {product_name}")
                continue

            alias_text = row["alias"].strip().lower()
            existing = db.execute(
                select(ProductAlias).where(
                    ProductAlias.product_id == product_id,
                    ProductAlias.alias == alias_text,
                )
            ).scalar_one_or_none()
            if existing:
                continue

            alias = ProductAlias(
                product_id=product_id,
                alias=alias_text,
                language=row.get("language", "").strip() or None,
                country=row.get("country", "").strip() or None,
                alias_type=row.get("alias_type", "").strip() or None,
            )
            db.add(alias)
            count += 1

    db.commit()
    print(f"  Aliases seeded: {count}")
    return count


def main():
    print("PharmaWatch seed script — pharma dictionary")
    engine = create_engine(settings.DATABASE_SYNC_URL)

    with Session(engine) as db:
        print("Seeding categories…")
        category_map = seed_categories(db)

        print("Seeding brands…")
        brand_map = seed_brands(db)

        print("Seeding products…")
        product_map = seed_products(db, brand_map, category_map)

        print("Seeding aliases…")
        seed_aliases(db, product_map)

    print("Done. Pharma dictionary loaded successfully.")


if __name__ == "__main__":
    main()
