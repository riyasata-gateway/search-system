"""Enrich brand-linked news mentions with the full ARTICLE BODY (we store only
the headline). Fetches each source_url and extracts the main text with
trafilatura. Best-effort: paywalls / 404s / JS-only pages are skipped (the
headline stays). Idempotent (skips already-long). Bounded per-fetch timeout so
one slow site can't stall the run.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import trafilatura
from sqlalchemy import create_engine, text
from core.config import settings

DONE_LEN = 400


def main():
    eng = create_engine(settings.DATABASE_SYNC_URL)
    with eng.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT m.id::text mid, m.source_url url,
                   coalesce(m.clean_text, m.raw_text) body
            FROM mentions m JOIN mention_entities me ON me.mention_id = m.id AND me.entity_type='brand'
            WHERE m.source_type IN ('rss','news') AND m.is_deleted=false AND m.source_url IS NOT NULL
        """)).fetchall()
    todo = [(r[0], r[1], r[2]) for r in rows if len(r[2] or "") < DONE_LEN]
    print(f"linked news: {len(rows)} | to enrich: {len(todo)}")

    eng2 = create_engine(settings.DATABASE_SYNC_URL)
    done = ok = 0
    for mid, url, body in todo:
        done += 1
        try:
            dl = trafilatura.fetch_url(url)
            article = trafilatura.extract(dl, include_comments=False, include_tables=False) if dl else None
        except Exception:
            article = None
        if article and len(article) > 200:
            title = (body or "").split("\n")[0]
            merged = title + "\n\n" + article   # store COMPLETE article body
            with eng2.begin() as c:
                c.execute(text("UPDATE mentions SET clean_text=:t WHERE id::text=:id"), {"t": merged, "id": mid})
            ok += 1
        if done % 100 == 0:
            print(f"  {done}/{len(todo)} fetched · {ok} enriched")
    print(f"DONE: enriched {ok}/{len(todo)} news mentions with article bodies.")


if __name__ == "__main__":
    main()
