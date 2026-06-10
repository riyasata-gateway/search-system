"""Cross-brand KPI variance audit — detects the CLASS of data-integrity bugs:

  • brand-invariant   — a KPI that returns the SAME value for every brand
                        (a resolution / global-scope bug, like Total Reach was)
  • hardcoded-constant — a "score" that's actually a fixed lookup (e.g. lifecycle
                        fit: every 'growth' brand shows 95)
  • empty-rate        — how often a KPI has no value (sparse vs broken)

Computes the real engines (BPI, launch readiness, momentum, lifecycle, live KPI
grid) for a diverse brand sample and prints a per-metric verdict. Read-only.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import defaultdict
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from core.config import settings
from models.brand import Brand
from intelligence.framework_kpis import compute_live_values
from intelligence.launch_readiness import compute_launch_readiness
from intelligence.brand_potential_index import compute_bpi
from intelligence.momentum import compute_momentum
from intelligence.lifecycle import classify_lifecycle


def main():
    eng = create_engine(settings.DATABASE_SYNC_URL)
    with Session(eng) as db:
        # Diverse sample: highest-linked brands + a few catalog ones.
        top = db.execute(text("""
            SELECT me.entity_id, count(*) n FROM mention_entities me
            WHERE me.entity_type='brand' GROUP BY me.entity_id ORDER BY n DESC LIMIT 12
        """)).fetchall()
        ids = [r[0] for r in top]
        brands = [db.get(Brand, i) for i in ids]
        print("Sample brands:", [b.name for b in brands])

        # Collect per-brand metric values.
        metric_vals = defaultdict(list)   # metric label -> [(brand, value)]
        for b in brands:
            try:
                lr = compute_launch_readiness(db, b.id)
                if lr:
                    for m in lr.to_bundle().metrics:
                        metric_vals[f"launch:{m.label.split(':')[0]}"].append((b.name, m.value))
            except Exception as e:
                print(f"  launch err {b.name}: {e}")
            try:
                bpi = compute_bpi(db, b.id)
                if bpi:
                    c = bpi.components
                    for k in ("awareness", "adoption", "sentiment", "market_fit"):
                        metric_vals[f"bpi:{k}"].append((b.name, round(getattr(c, k), 3)))
                    metric_vals["bpi:score"].append((b.name, round(bpi.score, 1)))
            except Exception as e:
                print(f"  bpi err {b.name}: {e}")
            try:
                mo = compute_momentum(db, "brand", b.id)
                metric_vals["momentum"].append((b.name, round(mo.score, 1) if mo else None))
            except Exception as e:
                print(f"  mom err {b.name}: {e}")
            try:
                lc = classify_lifecycle(db, "brand", b.id)
                metric_vals["lifecycle:stage"].append((b.name, lc.stage.value))
            except Exception as e:
                print(f"  lc err {b.name}: {e}")

        print("\n=== METRIC VARIANCE VERDICT ===")
        for label in sorted(metric_vals):
            vals = [v for _, v in metric_vals[label]]
            present = [v for v in vals if v is not None]
            distinct = set(present)
            empty = sum(1 for v in vals if v is None)
            if not present:
                verdict = "ALL EMPTY"
            elif len(distinct) == 1:
                verdict = f"⚠ BRAND-INVARIANT (all={next(iter(distinct))})"
            elif len(distinct) <= 3 and len(present) >= 6:
                verdict = f"⚠ LOW-VARIANCE / likely-constant {sorted(distinct)}"
            else:
                verdict = f"ok ({len(distinct)} distinct)"
            print(f"  {label:22} empty={empty}/{len(vals)}  {verdict}")
            if "INVARIANT" in verdict or "LOW-VARIANCE" in verdict:
                print(f"       values: {metric_vals[label]}")


if __name__ == "__main__":
    main()