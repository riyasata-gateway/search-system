"""Step 1 of the semantic-insights slice — backfill full PubMed ABSTRACTS.

The PubMed connector stores only the article title (esummary). The abstract —
the actual findings text we want to mine — is fetched here via NCBI efetch (we
already hold the PMIDs in raw_metadata) and folded into clean_text so it becomes
embeddable / retrievable. KPIs that merely COUNT pubmed are unaffected.

Idempotent: skips mentions whose text already looks abstract-length unless
--force. Usage: .venv/bin/python scripts/enrich_pubmed_abstracts.py
"""
import os, sys, time, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import xml.etree.ElementTree as ET
import httpx
from sqlalchemy import create_engine, text
from core.config import settings

EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
BATCH = 40
ABSTRACT_LOOKS_DONE = 400   # chars — above this we assume already enriched


def _fetch_abstracts(pmids):
    """Return {pmid: abstract_text} for a batch of PMIDs via efetch."""
    out = {}
    r = httpx.get(EFETCH, params={"db": "pubmed", "id": ",".join(pmids),
                                  "rettype": "abstract", "retmode": "xml"}, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    for art in root.findall(".//PubmedArticle"):
        pmid_el = art.find(".//MedlineCitation/PMID")
        if pmid_el is None:
            continue
        pmid = (pmid_el.text or "").strip()
        chunks = []
        for ab in art.findall(".//Abstract/AbstractText"):
            label = ab.get("Label")
            txt = "".join(ab.itertext()).strip()
            if txt:
                chunks.append(f"{label}: {txt}" if label else txt)
        if chunks:
            out[pmid] = " ".join(chunks)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-enrich even if text already long")
    args = ap.parse_args()

    eng = create_engine(settings.DATABASE_SYNC_URL)
    with eng.begin() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT m.id, m.raw_metadata->>'pmid' AS pmid,
                   coalesce(m.clean_text, m.raw_text) AS body
            FROM mentions m
            JOIN mention_entities me ON me.mention_id = m.id AND me.entity_type = 'brand'
            WHERE m.source_type = 'pubmed' AND m.is_deleted = false
              AND m.raw_metadata->>'pmid' IS NOT NULL
        """)).fetchall()
        todo = [(r[0], r[1], r[2]) for r in rows
                if args.force or len(r[2] or "") < ABSTRACT_LOOKS_DONE]
        print(f"pubmed mentions: {len(rows)} | to enrich: {len(todo)}")

        # pmid -> [(mention_id, current_title)]
        by_pmid = {}
        for mid, pmid, body in todo:
            by_pmid.setdefault(pmid, []).append((mid, body or ""))

        pmids = list(by_pmid)
        enriched = 0
        for i in range(0, len(pmids), BATCH):
            batch = pmids[i:i + BATCH]
            try:
                abstracts = _fetch_abstracts(batch)
            except Exception as e:
                print(f"  batch {i//BATCH} efetch error: {e}")
                continue
            for pmid, abstract in abstracts.items():
                for mid, title in by_pmid.get(pmid, []):
                    # Title first (keeps it searchable) + the COMPLETE abstract.
                    merged = title.split("\n")[0].strip() + "\n\n" + abstract
                    conn.execute(text("UPDATE mentions SET clean_text = :t WHERE id = :id"),
                                 {"t": merged, "id": mid})
                    enriched += 1
            print(f"  {min(i+BATCH, len(pmids))}/{len(pmids)} PMIDs · {enriched} mentions enriched")
            time.sleep(0.4)   # NCBI courtesy rate limit (no API key)
        print(f"DONE: enriched {enriched} pubmed mentions with abstracts.")


if __name__ == "__main__":
    main()
