from datetime import datetime, timezone
from typing import List, Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import settings
from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

COUNTRY_GEO_MAP = {
    "BE": "BE",
    "FR": "FR",
    "NL": "NL",
    "DE": "DE",
}


class GoogleTrendsConnector(BaseConnector):
    source_type = "google_trends"

    def __init__(self):
        from pytrends.request import TrendReq
        # Strip whitespace; treat empty/comment-only values as "no proxy".
        # An env loader that doesn't strip inline `# ...` comments will leave them
        # in the value, which pytrends would then try to use as a real URL.
        proxy = (settings.GOOGLE_TRENDS_PROXY or "").strip()
        if proxy.startswith("#") or not proxy.lower().startswith(("http://", "https://", "socks5://")):
            proxy = ""
        proxies = [proxy] if proxy else []
        self._pytrends = TrendReq(hl="en-GB", tz=60, proxies=proxies, retries=3, backoff_factor=0.5)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=30))
    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        mentions: List[RawMention] = []

        kw_batches = [keywords[i:i + 5] for i in range(0, len(keywords), 5)]

        for country in countries:
            geo = COUNTRY_GEO_MAP.get(country, country)
            for batch in kw_batches:
                try:
                    self._pytrends.build_payload(batch, cat=0, timeframe="today 1-m", geo=geo)

                    interest_df = self._pytrends.interest_over_time()
                    if not interest_df.empty:
                        for kw in batch:
                            if kw in interest_df.columns:
                                series = interest_df[kw].dropna()
                                for ts, score in series.items():
                                    if score > 0:
                                        mentions.append(RawMention(
                                            source_type=self.source_type,
                                            source_url=f"https://trends.google.com/trends/explore?q={kw}&geo={geo}",
                                            country=country,
                                            language=None,
                                            published_at=datetime.combine(ts, datetime.min.time()).replace(tzinfo=timezone.utc),
                                            raw_text=f"Google Trends interest score for '{kw}' in {country}: {score}",
                                            query_used=kw,
                                            engagement_count=int(score),
                                        ))

                    related_queries = self._pytrends.related_queries()
                    for kw in batch:
                        kw_data = related_queries.get(kw, {})
                        for qtype in ("top", "rising"):
                            df = kw_data.get(qtype)
                            if df is not None and not df.empty:
                                for _, row in df.iterrows():
                                    query_text = row.get("query", "")
                                    value = row.get("value", 0)
                                    if query_text:
                                        mentions.append(RawMention(
                                            source_type=self.source_type,
                                            source_url=f"https://trends.google.com/trends/explore?q={query_text}&geo={geo}",
                                            country=country,
                                            language=None,
                                            published_at=datetime.now(timezone.utc),
                                            raw_text=f"Related {qtype} query for '{kw}' in {country}: {query_text} (value: {value})",
                                            query_used=kw,
                                            engagement_count=int(value) if isinstance(value, (int, float)) else None,
                                        ))

                    regional_interest = self._pytrends.interest_by_region(resolution="CITY", inc_low_vol=False)
                    if not regional_interest.empty:
                        for kw in batch:
                            if kw in regional_interest.columns:
                                top_cities = regional_interest[kw].nlargest(5)
                                for city, score in top_cities.items():
                                    if score > 0:
                                        mentions.append(RawMention(
                                            source_type=self.source_type,
                                            source_url=None,
                                            country=country,
                                            language=None,
                                            published_at=datetime.now(timezone.utc),
                                            raw_text=f"City-level interest for '{kw}' in {city}: {score}",
                                            query_used=kw,
                                            engagement_count=int(score),
                                            metadata={"city": city, "resolution": "CITY"},
                                        ))

                except Exception as exc:
                    logger.warning("google_trends_batch_failed", keywords=batch, country=country, error=str(exc))

        logger.info("google_trends_collected", count=len(mentions))
        return mentions

    def is_available(self) -> bool:
        return True
