from datetime import datetime, timezone
from typing import List

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

# Forum search endpoints. Each entry MUST have:
#   - a reachable host
#   - is_scraping_allowed=True (legal review done)
#   - robots_txt_checked=True (robots.txt verified)
#
# Both of the original entries (forum-sante.com, gezondheid.be) had failed:
# forum-sante.com is offline (DNS NXDOMAIN), gezondheid.be has retired its
# /zoeken/ search endpoint (404). Leaving the list empty makes the connector
# a no-op until a working endpoint is added — which is the correct behaviour
# until legal review re-approves a real host.
ALLOWED_FORUMS: List[dict] = []

HEADERS = {
    "User-Agent": "PharmaWatch/1.0 (pharmawatch@yourorg.com; EU pharma research bot; +https://pharmawatch.eu/bot)"
}


class ForumScraperConnector(BaseConnector):
    source_type = "forum"

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=2, min=5, max=20))
    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        if not ALLOWED_FORUMS:
            logger.info(
                "forum_scraper_no_hosts",
                detail="ALLOWED_FORUMS is empty; connector is a no-op until a legally-reviewed host is configured.",
            )
            return []

        mentions: List[RawMention] = []
        seen_urls: set = set()

        async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
            for forum in ALLOWED_FORUMS:
                if not forum.get("is_scraping_allowed") or not forum.get("robots_txt_checked"):
                    logger.warning(
                        "forum_scraping_skipped",
                        forum=forum["name"],
                        reason="robots_txt_checked or is_scraping_allowed not set",
                    )
                    continue

                if forum["country"] not in countries:
                    continue
                if forum["language"] not in languages:
                    continue

                for keyword in keywords:
                    try:
                        url = forum["search_url"].format(keyword=keyword)
                        resp = await client.get(url)
                        if resp.status_code != 200:
                            continue

                        soup = BeautifulSoup(resp.text, "html.parser")
                        result_links = soup.select("a[href]")

                        for link in result_links[:15]:
                            href = link.get("href", "")
                            if not href or href in seen_urls:
                                continue
                            if not href.startswith("http"):
                                href = forum["base_url"] + href

                            seen_urls.add(href)

                            try:
                                page_resp = await client.get(href)
                                if page_resp.status_code != 200:
                                    continue

                                import trafilatura
                                text = trafilatura.extract(
                                    page_resp.text,
                                    include_comments=False,
                                    no_fallback=False,
                                )
                                if not text or len(text) < 50:
                                    continue

                                mentions.append(RawMention(
                                    source_type=self.source_type,
                                    source_url=href,
                                    country=forum["country"],
                                    language=forum["language"],
                                    published_at=datetime.now(timezone.utc),
                                    raw_text=text,
                                    query_used=keyword,
                                    metadata={"forum": forum["name"]},
                                ))

                            except Exception as exc:
                                logger.warning("forum_page_failed", url=href, error=str(exc))

                    except Exception as exc:
                        logger.warning("forum_search_failed", forum=forum["name"], keyword=keyword, error=str(exc))

        logger.info("forum_scraper_collected", count=len(mentions))
        return mentions