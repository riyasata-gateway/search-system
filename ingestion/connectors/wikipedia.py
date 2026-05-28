"""Wikipedia connector — encyclopedic grounding for drug / molecule queries.

Free MediaWiki REST API (no key). Multilingual: fetches summaries from
en / fr / nl / de Wikipedias, matching PharmaWatch's EU language support.
"""
from typing import List
from urllib.parse import quote

import httpx

from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

# Only EU-supported languages are queried. Order roughly matches market priority.
WIKIPEDIA_LANG_DOMAINS = {
    "en": "en.wikipedia.org",
    "fr": "fr.wikipedia.org",
    "nl": "nl.wikipedia.org",
    "de": "de.wikipedia.org",
}

_HEADERS = {"User-Agent": "PharmaWatch/1.0 (https://pharmawatch.eu; contact@pharmawatch.eu)"}


class WikipediaConnector(BaseConnector):
    source_type = "wikipedia"

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        mentions: List[RawMention] = []
        seen_urls: set = set()

        target_langs = [l for l in languages if l in WIKIPEDIA_LANG_DOMAINS] or ["en"]

        async with httpx.AsyncClient(timeout=6.0, headers=_HEADERS) as client:
            for lang in target_langs:
                domain = WIKIPEDIA_LANG_DOMAINS[lang]
                for keyword in keywords:
                    try:
                        search_resp = await client.get(
                            f"https://{domain}/w/api.php",
                            params={
                                "action": "opensearch",
                                "search": keyword,
                                "limit": 3,
                                "namespace": 0,
                                "format": "json",
                            },
                        )
                        if search_resp.status_code != 200:
                            continue
                        data = search_resp.json()
                        # opensearch shape: [query, [titles], [descriptions], [urls]]
                        titles = data[1] if len(data) > 1 else []
                        descriptions = data[2] if len(data) > 2 else []
                        urls = data[3] if len(data) > 3 else []
                    except Exception as exc:
                        logger.warning(
                            "wikipedia_search_failed", keyword=keyword, lang=lang, error=str(exc)
                        )
                        continue

                    for title, desc, url in zip(titles, descriptions, urls):
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)

                        # REST summary endpoint returns a cleaner extract than opensearch desc.
                        extract = desc or ""
                        try:
                            summary_resp = await client.get(
                                f"https://{domain}/api/rest_v1/page/summary/{quote(title, safe='')}"
                            )
                            if summary_resp.status_code == 200:
                                payload = summary_resp.json()
                                better = payload.get("extract")
                                if better:
                                    extract = better
                        except Exception:
                            pass

                        text = f"{title}. {extract}".strip().rstrip(".")
                        if len(text) < 30:
                            continue

                        mentions.append(
                            RawMention(
                                source_type=self.source_type,
                                source_url=url,
                                country=None,
                                language=lang,
                                published_at=None,  # Wikipedia is evergreen reference
                                raw_text=text[:1200],
                                query_used=keyword,
                                engagement_count=None,
                                metadata={"title": title, "wiki_lang": lang},
                            )
                        )

        logger.info("wikipedia_collected", count=len(mentions))
        return mentions