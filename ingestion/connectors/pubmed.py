"""PubMed connector — biomedical literature grounding via NIH E-utilities.

Free, no key required (NCBI throttles to 3 req/s without an API key — acceptable
for our fan-out). Uses ESearch to find PMIDs then ESummary to fetch metadata.
"""
from datetime import datetime, timezone
from typing import List

import httpx

from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_HEADERS = {"User-Agent": "PharmaWatch/1.0"}


def _parse_pubdate(raw: str):
    """Parse a PubMed date string, returning ``(datetime | None, precision)``.

    PubMed dates are messy and frequently coarse: '2025 Mar 12', '2025 Mar',
    '2025', '2025 Spring'. A missing month/day cannot be recovered from the
    source, so year-only / month-only values resolve to the first of the period
    and are flagged via ``precision`` ('day' | 'month' | 'year') so downstream
    recency metrics can downweight or exclude dates that aren't day-accurate
    (otherwise ~13% of the corpus piles onto Jan-01 / the 1st of each month and
    fabricates daily spikes).
    """
    if not raw:
        return None, None
    raw = raw.strip()
    for fmt, precision in (("%Y %b %d", "day"), ("%Y %b", "month"), ("%Y", "year")):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc), precision
        except ValueError:
            continue
    # Last resort: a leading 4-digit year ('2025 Spring', '2025-2026', …).
    try:
        return datetime.strptime(raw[:4], "%Y").replace(tzinfo=timezone.utc), "year"
    except ValueError:
        return None, None


class PubMedConnector(BaseConnector):
    source_type = "pubmed"

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        mentions: List[RawMention] = []
        seen_pmids: set = set()

        async with httpx.AsyncClient(timeout=8.0, headers=_HEADERS) as client:
            for keyword in keywords:
                try:
                    search_resp = await client.get(
                        f"{EUTILS_BASE}/esearch.fcgi",
                        params={
                            "db": "pubmed",
                            "term": keyword,
                            "retmode": "json",
                            "retmax": 8,
                            "sort": "date",
                        },
                    )
                    if search_resp.status_code != 200:
                        continue
                    ids = (
                        search_resp.json()
                        .get("esearchresult", {})
                        .get("idlist", [])
                    )
                    new_ids = [pmid for pmid in ids if pmid not in seen_pmids]
                    if not new_ids:
                        continue
                    seen_pmids.update(new_ids)

                    summary_resp = await client.get(
                        f"{EUTILS_BASE}/esummary.fcgi",
                        params={
                            "db": "pubmed",
                            "id": ",".join(new_ids),
                            "retmode": "json",
                        },
                    )
                    if summary_resp.status_code != 200:
                        continue
                    result = summary_resp.json().get("result", {})
                except Exception as exc:
                    logger.warning("pubmed_query_failed", keyword=keyword, error=str(exc))
                    continue

                for pmid in new_ids:
                    entry = result.get(pmid)
                    if not entry:
                        continue
                    title = (entry.get("title") or "").strip()
                    if not title:
                        continue
                    journal = entry.get("fulljournalname") or entry.get("source") or ""
                    # Prefer epubdate (the real electronic-publication date) over
                    # pubdate (the journal *issue* date, which for ahead-of-print
                    # articles is routinely a future issue → published_at in the
                    # future). Fall back to pubdate only when epub is absent.
                    published_at, date_precision = _parse_pubdate(
                        entry.get("epubdate") or entry.get("pubdate") or ""
                    )
                    authors = [
                        a.get("name", "")
                        for a in (entry.get("authors") or [])[:3]
                        if a.get("name")
                    ]
                    parts = [title]
                    if journal:
                        parts.append(journal)
                    if authors:
                        parts.append(", ".join(authors))
                    text = ". ".join(parts).strip().rstrip(".")
                    if len(text) < 20:
                        continue
                    mentions.append(
                        RawMention(
                            source_type=self.source_type,
                            source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                            country=None,
                            language="en",  # PubMed titles are normalised to English
                            published_at=published_at,
                            raw_text=text[:800],
                            query_used=keyword,
                            engagement_count=None,
                            metadata={"pmid": pmid, "journal": journal,
                                      "date_precision": date_precision},
                        )
                    )

        logger.info("pubmed_collected", count=len(mentions))
        return mentions