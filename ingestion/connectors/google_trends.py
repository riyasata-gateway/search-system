import asyncio
import time
from datetime import datetime, timezone
from typing import List, Optional

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

# Google rate-limits unauthenticated pytrends hard (HTTP 429), especially from
# datacenter IPs. We defend with: a minimum interval between calls, exponential
# backoff on 429, an in-process cache (the batch repeats the same molecules across
# brands), and by issuing only the core interest-over-time call (related-queries is
# best-effort). For reliable bulk use set GOOGLE_TRENDS_PROXY to a residential proxy.
_MIN_INTERVAL = 2.5          # seconds between Google requests
_MAX_RETRIES = 3
_last_call = [0.0]
_CACHE: dict = {}            # (keyword_lower, geo) -> List[RawMention]


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
        self._pytrends = TrendReq(hl="fr-BE", tz=60, proxies=proxies)

    async def _throttle(self):
        wait = _MIN_INTERVAL - (time.time() - _last_call[0])
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call[0] = time.time()

    async def _interest(self, batch, geo):
        """interest_over_time with throttle + 429-aware exponential backoff."""
        for attempt in range(_MAX_RETRIES):
            await self._throttle()
            try:
                self._pytrends.build_payload(batch, cat=0, timeframe="today 1-m", geo=geo)
                return self._pytrends.interest_over_time()
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if "429" in msg or "rate" in msg.lower():
                    backoff = 5 * (2 ** attempt)
                    logger.warning("google_trends_rate_limited", attempt=attempt + 1,
                                   backoff=backoff, geo=geo, keywords=batch)
                    await asyncio.sleep(backoff)
                    continue
                logger.warning("google_trends_batch_failed", keywords=batch, geo=geo, error=msg)
                return None
        return None

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
                # Serve from the in-run cache where possible (the batch repeats the
                # same molecules across many brands).
                uncached = [kw for kw in batch if (kw.lower(), geo) not in _CACHE]
                for kw in batch:
                    if (kw.lower(), geo) in _CACHE:
                        mentions.extend(_CACHE[(kw.lower(), geo)])
                if not uncached:
                    continue

                interest_df = await self._interest(uncached, geo)
                if interest_df is None:
                    # Rate-limited/failed: cache an empty result so a large batch
                    # doesn't re-hammer Google for the same terms this run.
                    for kw in uncached:
                        _CACHE[(kw.lower(), geo)] = []
                    continue
                per_kw: dict = {kw: [] for kw in uncached}
                if not interest_df.empty:
                    for kw in uncached:
                        if kw in interest_df.columns:
                            for ts, score in interest_df[kw].dropna().items():
                                if score > 0:
                                    per_kw[kw].append(RawMention(
                                        source_type=self.source_type,
                                        source_url=f"https://trends.google.com/trends/explore?q={kw}&geo={geo}",
                                        country=country,
                                        language=None,
                                        published_at=datetime.combine(ts, datetime.min.time()).replace(tzinfo=timezone.utc),
                                        raw_text=f"Google Trends interest score for '{kw}' in {country}: {score}",
                                        query_used=kw,
                                        engagement_count=int(score),
                                    ))
                # Related queries — best-effort; never block the core signal on it.
                try:
                    related = self._pytrends.related_queries()
                    for kw in uncached:
                        for qtype in ("top", "rising"):
                            df = (related.get(kw) or {}).get(qtype)
                            if df is not None and not df.empty:
                                for _, row in df.iterrows():
                                    qt = row.get("query", "")
                                    if qt:
                                        per_kw[kw].append(RawMention(
                                            source_type=self.source_type,
                                            source_url=f"https://trends.google.com/trends/explore?q={qt}&geo={geo}",
                                            country=country, language=None,
                                            published_at=datetime.now(timezone.utc),
                                            raw_text=f"Related {qtype} query for '{kw}' in {country}: {qt} (value: {row.get('value', 0)})",
                                            query_used=kw,
                                            engagement_count=int(row.get("value", 0)) if isinstance(row.get("value"), (int, float)) else None,
                                        ))
                except Exception as exc:  # noqa: BLE001
                    logger.info("google_trends_related_skipped", error=str(exc))

                for kw in uncached:
                    _CACHE[(kw.lower(), geo)] = per_kw[kw]
                    mentions.extend(per_kw[kw])

        logger.info("google_trends_collected", count=len(mentions))
        return mentions

    def is_available(self) -> bool:
        return True
