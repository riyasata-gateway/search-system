import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import create_engine, text
from core.config import settings
from core.source_taxonomy import NAMESAKE_GATED_SOURCE_TYPES
from processing.brand_match import has_health_context, is_namesake_gated, AMBIGUOUS_BRAND_NAMES, _fold
from processing.llm_classifier import classify_brand_relevance
from intelligence.inn_resolver import resolve_inn

try:
    from scripts.build_sam_inn import BRAND_INN  # type: ignore
except Exception:
    BRAND_INN = {}

BATCH = 15          # texts per LLM call
WORKERS = 8         # parallel LLM calls


def _is_ambiguous(name) -> bool:
    return _fold(name or "") in AMBIGUOUS_BRAND_NAMES


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry-run)")
    args = ap.parse_args()

    eng = create_engine(settings.DATABASE_SYNC_URL)
    gated = list(NAMESAKE_GATED_SOURCE_TYPES)
    with eng.begin() as conn:
        rows = conn.execute(text("""
            SELECT me.id AS link_id, me.entity_id AS brand_id, b.name AS brand,
                   b.category, b.manufacturer, m.source_type,
                   coalesce(m.clean_text, m.raw_text) AS body
            FROM mention_entities me
            JOIN brands b ON b.id = me.entity_id
            JOIN mentions m ON m.id = me.mention_id
            WHERE me.entity_type = 'brand' AND m.source_type = ANY(:g)
        """), {"g": gated}).fetchall()
        print(f"news/social brand links: {len(rows)}")

        inn_cache: dict = {}
        to_delete: list = []
        by_brand: Counter = Counter()

        # ── 1) SUPPLIER brands → keyword/context gate (free) ─────────────────
        ambiguous_rows = defaultdict(list)   # brand -> [(link_id, body, manufacturer, category)]
        supplier_checked = 0
        for r in rows:
            if not is_namesake_gated(r.brand, r.category):
                continue  # coined framework brand — trusted
            if _is_ambiguous(r.brand):
                ambiguous_rows[r.brand].append(r)
                continue
            supplier_checked += 1
            inn = inn_cache.get(r.brand)
            if inn is None:
                inn = resolve_inn(r.brand, BRAND_INN.get(r.brand)) or []
                inn_cache[r.brand] = inn
            extra = list(inn) + ([r.manufacturer] if r.manufacturer else [])
            if not has_health_context(r.body or "", extra):
                to_delete.append(r.link_id)
                by_brand[r.brand] += 1
        print(f"supplier links keyword-checked: {supplier_checked} → {len(to_delete)} to drop")

        # ── 2) AMBIGUOUS framework brands → batched + parallel LLM ───────────
        ambiguous_total = sum(len(v) for v in ambiguous_rows.values())
        print(f"ambiguous-brand links for LLM: {ambiguous_total} across {len(ambiguous_rows)} brands")

        tasks = []   # (brand, context, [rows-chunk])
        for brand, brs in ambiguous_rows.items():
            mfr = next((x.manufacturer for x in brs if x.manufacturer), "")
            cat = next((x.category for x in brs if x.category), "")
            ctx = " / ".join([c for c in (cat, mfr) if c]) or "pharma/dermocosmetic brand"
            for i in range(0, len(brs), BATCH):
                tasks.append((brand, ctx, brs[i:i + BATCH]))

        def run(task):
            brand, ctx, chunk = task
            verdicts = classify_brand_relevance(brand, ctx, [c.body or "" for c in chunk])
            drop = [chunk[i].link_id for i, ok in enumerate(verdicts) if not ok]
            return brand, drop

        if tasks:
            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                for fut in as_completed([ex.submit(run, t) for t in tasks]):
                    brand, drop = fut.result()
                    to_delete.extend(drop)
                    by_brand[brand] += len(drop)

        print(f"\ntotal misattributed: {len(to_delete)} links across {len(by_brand)} brands")
        print("top dropped brands:")
        for nm, n in by_brand.most_common(20):
            print(f"  {nm:18} {n}")

        if args.apply and to_delete:
            for i in range(0, len(to_delete), 1000):
                conn.execute(text("DELETE FROM mention_entities WHERE id = ANY(:ids)"),
                             {"ids": to_delete[i:i + 1000]})
            print(f"\nDELETED {len(to_delete)} misattributed brand links.")
        elif to_delete:
            print("\n(dry-run — re-run with --apply to delete)")


if __name__ == "__main__":
    main()