"""Build the canonical CNK-keyed pack registry (bilingual, pack-aware).

Fuses, by CNK (the language-independent Belgian pack code):
  • SAM pack_index.json  → FR + NL names, active substance, ATC, kind, brand
  • Farmaline catalogue   → retail facts (price, promo, stock, rating, url, EAN, form)

One row per CNK → the same pack listed in FR and NL, or in SAM vs a retail
catalogue, collapses to a single canonical entity instead of duplicating. Only
framework brands are registered (brand_id linked).

Usage:  .venv/bin/python scripts/build_pack_registry.py --csv <farmaline.csv>
"""
import argparse
import csv
import json
import os
import sys
import unicodedata
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from core.config import settings
from models.brand import Brand
from models.pack import Pack

PACK_INDEX = "data/sam/pack_index.json"


def _deaccent(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn").lower().strip()


def _candidates(name):
    cands = {name}
    if "/" in name:
        cands.update(p.strip() for p in name.split("/"))
    if "(" in name:
        cands.add(name.split("(")[0].strip())
        inside = name[name.find("(") + 1:name.rfind(")")]
        cands.update(p.strip() for p in inside.replace(" brands", "").split(","))
    return sorted({_deaccent(c) for c in cands if len(c) >= 3})


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _norm(cnk):
    return (cnk or "").strip().lstrip("0")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    args = ap.parse_args()

    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        brands = db.execute(select(Brand).where(Brand.category.isnot(None))).scalars().all()
    name_to_id = {b.name: b.id for b in brands}
    cand_to_brand = {}
    for b in brands:
        for c in _candidates(b.name):
            cand_to_brand[c] = b.name

    sam = json.load(open(PACK_INDEX, encoding="utf-8"))  # already normalised CNK keys

    # packs: cnk -> merged record. Seed from SAM (FR/NL/substance/atc), then layer Farmaline.
    packs = {}
    for cnk, s in sam.items():
        packs[cnk] = {"cnk": cnk, "brand_name": s.get("brand"), "name_fr": s.get("fr"),
                      "name_nl": s.get("nl"), "active_substance": s.get("substance"),
                      "atc": s.get("atc"), "kind": s.get("kind"), "sources": ["sam"]}

    rows = farma_matched = 0
    with open(args.csv, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            rows += 1
            bn = cand_to_brand.get(_deaccent(r.get("brand", "")))
            if not bn:
                continue  # only framework brands
            farma_matched += 1
            cnk = _norm(r.get("cnk"))
            if not cnk:
                continue
            p = packs.get(cnk) or {"cnk": cnk, "brand_name": bn, "sources": []}
            p.setdefault("brand_name", bn)
            p["name_fr"] = p.get("name_fr") or (r.get("title") or "").strip() or None
            p["active_substance"] = p.get("active_substance") or (r.get("active_substance") or "").strip() or None
            p["category"] = (r.get("category_lvl0") or "").strip() or None
            p["pharma_form"] = (r.get("pharma_form") or "").strip() or None
            p["ean"] = (r.get("ean") or "").strip() or None
            p["is_prescription"] = (r.get("is_prescription", "").strip().lower() in ("yes", "true", "1"))
            p["price"] = _f(r.get("price"))
            p["old_price"] = _f(r.get("old_price"))
            p["in_stock"] = (r.get("in_stock", "").strip().lower() in ("true", "1", "yes"))
            p["rating"] = _f(r.get("rating"))
            rc = _f(r.get("rating_count"))
            p["rating_count"] = int(rc) if rc else None
            p["product_url"] = (r.get("product_url") or "").strip() or None
            p.setdefault("kind", "parapharmacy")
            if "farmaline" not in p.get("sources", []):
                p["sources"] = (p.get("sources") or []) + ["farmaline"]
            packs[cnk] = p

    # write
    with Session(engine) as db:
        db.execute(text("DELETE FROM packs"))
        n = 0
        for cnk, p in packs.items():
            bn = p.get("brand_name")
            db.add(Pack(cnk=cnk, brand_id=name_to_id.get(bn), brand_name=bn,
                        name_fr=(p.get("name_fr") or "")[:512] or None,
                        name_nl=(p.get("name_nl") or "")[:512] or None,
                        active_substance=(p.get("active_substance") or "")[:256] or None,
                        atc=p.get("atc"), category=(p.get("category") or "")[:160] or None,
                        pharma_form=(p.get("pharma_form") or "")[:160] or None,
                        ean=p.get("ean"), kind=p.get("kind"),
                        is_prescription=p.get("is_prescription"), price=p.get("price"),
                        old_price=p.get("old_price"), in_stock=p.get("in_stock"),
                        rating=p.get("rating"), rating_count=p.get("rating_count"),
                        product_url=(p.get("product_url") or "")[:1024] or None,
                        sources=p.get("sources")))
            n += 1
            if n % 2000 == 0:
                db.commit()
        db.commit()

        bilingual = sum(1 for p in packs.values() if p.get("name_fr") and p.get("name_nl"))
        both_src = sum(1 for p in packs.values() if len(p.get("sources", [])) > 1)
        print(f"Farmaline rows scanned: {rows}, framework-brand rows: {farma_matched}")
        print(f"Canonical CNK packs: {n}  (bilingual FR+NL: {bilingual}, in ≥2 sources: {both_src})")
        print("\nPer-brand canonical pack counts:")
        for bn, c in sorted(db.execute(text(
            "SELECT brand_name, count(*) FROM packs GROUP BY brand_name ORDER BY 2 DESC")).all(),
                key=lambda x: -x[1])[:15]:
            print(f"  {bn:30s} {c}")


if __name__ == "__main__":
    main()
