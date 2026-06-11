"""Ingest the Farmaline product catalogue → per-brand retail intelligence.

This is the Belgian pharmacy retail pack-layer the public regulatory sources don't
give us (and that matters most for dermo/supplements): price, promo/discount,
stock, online rating + review count, pack forms, dermo attributes — all keyed by
CNK so it joins to SAM. Aggregated per framework brand into
`data/farmaline/brand_retail.json` (read live by the KPI layer).

Usage:  .venv/bin/python scripts/ingest_farmaline_catalogue.py --csv <path>
"""
import argparse
import csv
import json
import os
import sys
import unicodedata
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from models.brand import Brand

OUT = "data/farmaline/brand_retail.json"

# Benefit / claim vocabulary (FR / NL / EN) for the claims-taxonomy KPI — scanned
# over Farmaline product descriptions (the richest structured claims source).
BENEFIT_TERMS = {
    "Hydration": ["hydrat", "moistur", "vocht"],
    "Anti-aging": ["anti-âge", "anti-age", "rides", "wrinkle", "verouder", "rimpel"],
    "Soothing": ["apais", "soothing", "calming", "kalmer"],
    "Sun / SPF": ["solaire", "spf", " uv", "sunscreen", "zon"],
    "Sensitive skin": ["sensible", "sensitive", "gevoelige"],
    "Repair / barrier": ["répar", "repair", "cicatris", "herstel", "barrière", "barrier"],
    "Radiance": ["éclat", "radiance", "glow", "glans"],
    "Mattifying / oily": ["matif", "matt", "grasse", "vette", "oily", "imperfection", "acné", "acne"],
    "Firming": ["fermeté", "firming", "verstevig"],
    "Energy / vitality": ["énergie", "energy", "vitalit", "energie"],
    "Immunity": ["immunit", "immune", "immuun", "défenses", "afweer"],
    "Sleep / stress": ["sommeil", "sleep", "slaap", "stress", "détente"],
    "Digestion / transit": ["digestion", "digestive", "transit", "spijsver", "maag"],
}


def _deaccent(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower().strip()


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    args = ap.parse_args()

    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        brands = db.execute(select(Brand).where(Brand.category.isnot(None))).scalars().all()
    cand_to_brand = {}
    for b in brands:
        for c in _candidates(b.name):
            cand_to_brand[c] = b.name

    agg = defaultdict(lambda: {"skus": 0, "prices": [], "discounts": [], "promo": 0,
                               "in_stock": 0, "rx": 0, "ratings": [], "rating_count": 0,
                               "cnk": set(), "forms": set(), "cats": defaultdict(int),
                               "skin_types": defaultdict(int), "uv": defaultdict(int),
                               "benefits": defaultdict(int)})
    rows = 0
    with open(args.csv, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            rows += 1
            brand_raw = _deaccent(r.get("brand", ""))
            bn = cand_to_brand.get(brand_raw)
            if not bn:
                # also try prefix match (e.g. "la roche-posay laboratoire")
                bn = next((cand_to_brand[c] for c in cand_to_brand if brand_raw == c), None)
            if not bn:
                continue
            a = agg[bn]
            a["skus"] += 1
            p = _f(r.get("price"))
            if p:
                a["prices"].append(p)
            disc = _f(r.get("online_discount"))
            if disc and disc > 0:
                a["discounts"].append(disc); a["promo"] += 1
            if (r.get("in_stock", "").strip().lower() in ("true", "1", "yes")):
                a["in_stock"] += 1
            if (r.get("is_prescription", "").strip().lower() in ("yes", "true", "1")):
                a["rx"] += 1
            rt = _f(r.get("rating"))
            rc = _f(r.get("rating_count"))
            if rt and rc:
                a["ratings"].append((rt, rc)); a["rating_count"] += int(rc)
            if r.get("cnk"):
                a["cnk"].add(r["cnk"].strip())
            if r.get("pharma_form"):
                a["forms"].add(r["pharma_form"].strip())
            c0 = r.get("category_lvl0", "").strip()
            if c0:
                a["cats"][c0] += 1
            st = r.get("skin_type", "").strip()
            if st:
                a["skin_types"][st] += 1
            uv = r.get("uv_protection", "").strip()
            if uv:
                a["uv"][uv] += 1
            blob = (r.get("description", "") + " " + r.get("title", "") + " " +
                    r.get("product_type", "")).lower()
            for benefit, terms in BENEFIT_TERMS.items():
                if any(t in blob for t in terms):
                    a["benefits"][benefit] += 1

    result = {}
    for bn, a in agg.items():
        prices = a["prices"]
        wr = sum(rt * rc for rt, rc in a["ratings"])
        wn = sum(rc for _, rc in a["ratings"])
        result[bn] = {
            "skus": a["skus"],
            "price": ({"min": round(min(prices), 2), "max": round(max(prices), 2),
                       "avg": round(sum(prices) / len(prices), 2)} if prices else None),
            "promo_pct": round(100 * a["promo"] / a["skus"]) if a["skus"] else 0,
            "avg_discount": round(sum(a["discounts"]) / len(a["discounts"])) if a["discounts"] else 0,
            "in_stock_pct": round(100 * a["in_stock"] / a["skus"]) if a["skus"] else 0,
            "rx_pct": round(100 * a["rx"] / a["skus"]) if a["skus"] else 0,
            "rating": round(wr / wn, 2) if wn else None,
            "rating_count": a["rating_count"],
            "top_category": max(a["cats"], key=a["cats"].get) if a["cats"] else None,
            "forms": sorted(a["forms"])[:8],
            "cnk_count": len(a["cnk"]),
            # claims / benefit taxonomy (share of the brand's SKUs per theme)
            "benefits": [{"name": k, "share": round(100 * v / a["skus"])}
                         for k, v in sorted(a["benefits"].items(), key=lambda x: -x[1])[:6]],
            "skin_types": [{"name": k, "share": round(100 * v / a["skus"])}
                           for k, v in sorted(a["skin_types"].items(), key=lambda x: -x[1])[:4]],
            "uv": [{"name": k, "share": round(100 * v / a["skus"])}
                   for k, v in sorted(a["uv"].items(), key=lambda x: -x[1])[:3]],
        }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    print(f"Scanned {rows} Farmaline products. Matched {len(result)} framework brands:")
    for b in sorted(result, key=lambda x: -result[x]["skus"]):
        r = result[b]
        pr = f"€{r['price']['min']}-{r['price']['max']}" if r["price"] else "—"
        print(f"  {b:30s} SKUs={r['skus']:4d} price={pr:14s} promo={r['promo_pct']}% stock={r['in_stock_pct']}% "
              f"rating={r['rating']}({r['rating_count']})")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
