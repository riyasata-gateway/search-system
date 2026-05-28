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
    """PubMed pubdate is messy: '2025 Mar 12', '2025 Mar', '2025', '2025 Spring'.
    Try the structured formats first, then fall back to year-only.
    """
    if not raw:
        return None
    for fmt in ("%Y %b %d", "%Y %b", "%Y"):
        try:
            return datetime.strptime(raw[: len(fmt) + 6], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    head = raw.split(" ", 1)[0]
    try:
        return datetime.strptime(head, "%Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


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
                    published_at = _parse_pubdate(entry.get("pubdate") or entry.get("epubdate") or "")
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
                            metadata={"pmid": pmid, "journal": journal},
                        )
                    )

        logger.info("pubmed_collected", count=len(mentions))
        return mentions