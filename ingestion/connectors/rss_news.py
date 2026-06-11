from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from urllib.parse import quote_plus

import feedparser
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

# (language, country, ceid) — Google News RSS locales that cover Phase-1 markets
# (Belgium + France) plus the cross-lingual neighbours that share supply chains.
LOCALES = [
    ("fr", "FR", "FR:fr"),
    ("fr", "BE", "BE:fr"),
    ("nl", "BE", "BE:nl"),
    ("nl", "NL", "NL:nl"),
    ("de", "DE", "DE:de"),
    ("en", "GB", "GB:en"),
]

# Curated topical feeds that don't depend on a keyword query — they get tried
# in addition to Google News RSS so EMA-style regulatory updates flow in even
# when no brand-specific keyword matches.
TOPICAL_FEEDS = [
    {"url": "https://www.ema.europa.eu/en/news/rss.xml", "country": None, "language": "en"},
]


def _fetch_one_feed(
    url: str,
    country: Optional[str],
    language: Optional[str],
    keywords_lower: List[str],
    query_used: Optional[str],
) -> List[RawMention]:
    out: List[RawMention] = []
    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        logger.warning("rss_feed_failed", feed=url, error=str(exc))
        return out

    for entry in feed.entries:
        link = getattr(entry, "link", None) or getattr(entry, "id", None)
        if not link:
            continue
        title = getattr(entry, "title", "") or ""
        summary = getattr(entry, "summary", "") or ""
        clean_summary = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)
        title_stub = title.lower()[:60]
        if clean_summary and not clean_summary.lower().startswith(title_stub):
            text = f"{title}. {clean_summary}".strip().rstrip(".")
        else:
            text = title.strip()
        if len(text) < 20:
            continue

        # For Google News RSS the keyword filter is already applied server-side
        # (q=keyword), so we only apply the keyword screen to the topical feeds.
        if query_used is None:
            text_lower = text.lower()
            matched = next((k for k in keywords_lower if k in text_lower), None)
            if not matched:
                continue
            query_used_local = matched
        else:
            query_used_local = query_used

        published_at = None
        if hasattr(entry, "published"):
            try:
                published_at = parsedate_to_datetime(entry.published)
            except Exception:
                published_at = None

        out.append(RawMention(
            source_type="rss",
            source_url=link,
            country=country,
            language=language,
            published_at=published_at,
            raw_text=text[:1500],
            query_used=query_used_local,
            metadata={"feed_url": url},
        ))
    return out


class RSSNewsConnector(BaseConnector):
    """Pulls news via Google News RSS per keyword × locale + a small set of
    curated topical feeds (EMA regulatory updates).

    Why Google News instead of a hardcoded publisher list: the publisher RSS
    URLs that used to live here (lequotidiendupharmacien, apb.be, figarosante,
    rtl.be …) had all rotted to 404/DNS-fail, so the connector was returning
    zero rows on every run. Google News RSS is stable, supports keyword queries
    server-side, and gives us multi-publisher coverage for free.
    """

    source_type = "rss"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        if not keywords:
            return []

        keywords_lower = [k.lower() for k in keywords]
        seen_urls: set = set()

        # Build (url, country, language, query_used) tuples for parallel fetch.
        # `query_used=None` flags "apply keyword filter post-fetch" — used only
        # for topical feeds that don't accept a query parameter.
        tasks: List[tuple] = []
        for keyword in keywords:
            for lang, geo, ceid in LOCALES:
                if lang not in languages and geo not in countries:
                    continue
                url = (
                    "https://news.google.com/rss/search"
                    f"?q={quote_plus(keyword)}&hl={lang}&gl={geo}&ceid={ceid}"
                )
                tasks.append((url, geo, lang, keywords_lower, keyword))

        for feed_cfg in TOPICAL_FEEDS:
            if feed_cfg["language"] and feed_cfg["language"] not in languages:
                continue
            tasks.append((
                feed_cfg["url"],
                feed_cfg["country"],
                feed_cfg["language"],
                keywords_lower,
                None,  # apply keyword filter post-fetch
            ))

        mentions: List[RawMention] = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(_fetch_one_feed, url, country, language, kws_lower, q)
                for (url, country, language, kws_lower, q) in tasks
            ]
            for fut in futures:
                try:
                    for rm in fut.result(timeout=12) or []:
                        if rm.source_url in seen_urls:
                            continue
                        seen_urls.add(rm.source_url)
                        mentions.append(rm)
                except Exception as exc:
                    logger.warning("rss_fetch_task_failed", error=str(exc))

        logger.info("rss_news_collected", count=len(mentions), tasks=len(tasks))
        return mentions