"""Remediate historical brand attributions created by the old "link to the
queried brand, no matter the text" logic (see ingest_framework_brands.py history).

Rules — identical to the new ingestion gate:
  • REVIEW sources (farmaline, medimarket): never touched. The link is an exact
    `brand_name` match, validated at import, and the brand rarely appears in the
    review *body* — so a text check would wrongly drop them.
  • EVIDENCE / substance sources (pubmed, clinical_trials, openfda, eudravigilance,
    bcfi, bcfi_cbip, ansm_shortage, belgium_health, fagg_shortage):
      – brand is a medicine (has a Belgian INN)  → molecule-level evidence link:
        KEEP but downgrade confidence to 0.5; DELETE if the mention fans out to
        more than MAX_EVIDENCE_FANOUT brands (a general/substance article).
      – brand is NOT a medicine                  → it was queried by trade name,
        so KEEP only if the name actually appears in the text, else DELETE.
  • CONSUMER-TEXT sources (rss, news, youtube, forum, wikipedia, brand_site,
    doctissimo, reddit, app_store): KEEP only if the brand name appears in the
    text (word-boundary), else DELETE — these are the 90%+ name-absent FPs.

Dry-run by default; pass --apply to execute. Transactional.

Usage:  .venv/bin/python scripts/reattribute_mentions.py [--apply]
"""
import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

from core.config import settings
from intelligence.inn_resolver import is_belgian_medicine
from processing.brand_match import brand_terms, text_mentions_brand

REVIEW_SOURCES = {"farmaline", "medimarket"}
EVIDENCE_SOURCES = {
    "pubmed", "clinical_trials", "openfda", "eudravigilance", "bcfi",
    "bcfi_cbip", "ansm_shortage", "belgium_health", "fagg_shortage",
}
MAX_EVIDENCE_FANOUT = 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="execute (default: dry-run)")
    args = ap.parse_args()

    engine = create_engine(settings.DATABASE_SYNC_URL)

    # All non-review brand links + their mention text, source, and fan-out.
    sql = text("""
        SELECT me.id AS link_id, me.entity_id, b.name AS brand_name,
               m.source_type,
               lower(coalesce(m.clean_text, m.raw_text, '')) AS body,
               cnt.nbrands
        FROM mention_entities me
        JOIN brands b ON b.id = me.entity_id
        JOIN mentions m ON m.id = me.mention_id
        JOIN (SELECT mention_id, count(*) AS nbrands
              FROM mention_entities WHERE entity_type='brand'
              GROUP BY mention_id) cnt ON cnt.mention_id = me.mention_id
        WHERE me.entity_type='brand'
          AND m.source_type NOT IN ('farmaline','medimarket')
    """)

    med_cache: dict[str, bool] = {}
    def _is_med(name: str) -> bool:
        if name not in med_cache:
            med_cache[name] = bool(is_belgian_medicine(name))
        return med_cache[name]

    to_delete: list[int] = []
    to_downgrade: list[int] = []
    stats = defaultdict(lambda: defaultdict(int))  # source_type -> action -> n

    with engine.connect() as conn:
        rows = conn.execute(sql)
        for r in rows:
            terms = brand_terms(r.brand_name)
            named = text_mentions_brand(r.body, terms)
            src = r.source_type or "?"

            if src in EVIDENCE_SOURCES:
                if _is_med(r.brand_name):
                    if r.nbrands > MAX_EVIDENCE_FANOUT:
                        to_delete.append(r.link_id); action = "delete:fanout"
                    else:
                        to_downgrade.append(r.link_id); action = "keep:evidence0.5"
                else:
                    if named:
                        action = "keep:named"
                    else:
                        to_delete.append(r.link_id); action = "delete:nonmed-collision"
            else:  # consumer-text
                if named:
                    action = "keep:named"
                else:
                    to_delete.append(r.link_id); action = "delete:name-absent"
            stats[src][action] += 1

    # ── Report ────────────────────────────────────────────────────────────────
    print(f"\n{'source':16s} {'action':26s} {'links':>8s}")
    print("-" * 54)
    tot_del = tot_dg = tot_keep = 0
    for src in sorted(stats):
        for action in sorted(stats[src]):
            n = stats[src][action]
            print(f"{src:16s} {action:26s} {n:8d}")
            if action.startswith("delete"):
                tot_del += n
            elif action.startswith("keep:evidence"):
                tot_dg += n
            else:
                tot_keep += n
    print("-" * 54)
    print(f"{'TOTAL':16s} {'delete':26s} {tot_del:8d}")
    print(f"{'':16s} {'downgrade→0.5':26s} {tot_dg:8d}")
    print(f"{'':16s} {'keep (named)':26s} {tot_keep:8d}")

    if not args.apply:
        print("\n[dry-run] nothing changed. Re-run with --apply to execute.")
        return

    with engine.begin() as conn:
        for i in range(0, len(to_delete), 5000):
            conn.execute(
                text("DELETE FROM mention_entities WHERE id = ANY(:ids)"),
                {"ids": to_delete[i:i + 5000]},
            )
        for i in range(0, len(to_downgrade), 5000):
            conn.execute(
                text("UPDATE mention_entities SET confidence=0.5 WHERE id = ANY(:ids)"),
                {"ids": to_downgrade[i:i + 5000]},
            )
    print(f"\n[applied] deleted {len(to_delete)} false links, "
          f"downgraded {len(to_downgrade)} evidence links to 0.5.")


if __name__ == "__main__":
    main()