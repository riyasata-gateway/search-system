"""Soft-delete orphan news mentions — unlinked rss/news rows with NO entity
attribution at all (brand or product).

These are the residue of the namesake-misattribution purge (links removed, the
article rows kept) plus wide-net fetches (celebrities, narcotics, common
surnames) that never matched a pharma brand. They're inert — touch no KPI — but
bloat the table and the unclassified pool. Soft-delete (is_deleted=true) takes
them out of every query (all queries filter is_deleted=false) and is reversible.

Dry-run by default; pass --apply to act.
"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import create_engine, text
from core.config import settings

# An orphan = no mention_entities row of ANY entity_type.
WHERE = """
    m.source_type IN ('rss', 'news')
    AND m.is_deleted = false
    AND NOT EXISTS (SELECT 1 FROM mention_entities me WHERE me.mention_id = m.id)
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually soft-delete (default: dry-run)")
    ap.add_argument("--hard", action="store_true",
                    help="HARD-delete the rows instead of soft (cascades classifications "
                         "/ entities / AE candidates; search_results.mention_id → NULL). "
                         "Irreversible. Implies --apply.")
    args = ap.parse_args()

    eng = create_engine(settings.DATABASE_SYNC_URL)
    with eng.begin() as conn:
        n = conn.execute(text(f"SELECT count(*) FROM mentions m WHERE {WHERE}")).scalar()
        # Safety: confirm none of these are actually linked (defensive double-check).
        linked = conn.execute(text(f"""
            SELECT count(*) FROM mentions m
            WHERE m.source_type IN ('rss','news') AND m.is_deleted=false
              AND EXISTS (SELECT 1 FROM mention_entities me WHERE me.mention_id=m.id)
        """)).scalar()
        print(f"orphan news mentions to soft-delete: {n}")
        print(f"(sanity) LINKED news mentions that will be KEPT: {linked}")

        # The orphan set is defined by "no entity link", independent of the
        # is_deleted flag — so this also hard-removes rows already soft-deleted.
        HARD_WHERE = """
            m.source_type IN ('rss', 'news')
            AND NOT EXISTS (SELECT 1 FROM mention_entities me WHERE me.mention_id = m.id)
        """
        if args.hard:
            cls = conn.execute(text(f"""
                SELECT count(*) FROM mention_classifications mc
                WHERE EXISTS (SELECT 1 FROM mentions m WHERE m.id = mc.mention_id AND {HARD_WHERE})
            """)).scalar()
            done = conn.execute(text(f"DELETE FROM mentions m WHERE {HARD_WHERE}")).rowcount
            print(f"\nHARD-DELETED {done} orphan news mentions "
                  f"(+{cls} classification rows cascaded). Irreversible.")
        elif args.apply and n:
            done = conn.execute(text(f"UPDATE mentions m SET is_deleted = true WHERE {WHERE}")).rowcount
            print(f"\nSOFT-DELETED {done} orphan news mentions (reversible: is_deleted=true).")
        elif n:
            print("\n(dry-run — re-run with --apply to soft-delete, or --hard to remove)")


if __name__ == "__main__":
    main()
