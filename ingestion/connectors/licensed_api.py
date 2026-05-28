from datetime import datetime, timezone
from typing import List

import httpx

from core.config import settings
from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)


class LicensedAPIConnector(BaseConnector):
    """
    Tier 3 connector — licensed social data providers:
    Talkwalker, Meltwater, or Brandwatch API.
    Provides broad social/news/forum coverage across 30+ networks.
    Activated only when LICENSED_API_PROVIDER and LICENSED_API_KEY are set.

    The interface is intentionally generic — configure LICENSED_API_PROVIDER
    and adapt _fetch_mentions() to the specific provider's API shape.
    """
    source_type = "licensed_api"

    def is_available(self) -> bool:
        return bool(settings.LICENSED_API_KEY and settings.LICENSED_API_BASE_URL)

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        if not self.is_available():
            logger.info(
                "licensed_api_connector_disabled",
                reason="LICENSED_API_KEY or LICENSED_API_BASE_URL not configured",
            )
            return []

        provider = settings.LICENSED_API_PROVIDER or "generic"
        logger.info("licensed_api_collecting", provider=provider, keywords=keywords)

        mentions: List[RawMention] = []
        for keyword in keywords:
            try:
                raw = await self._fetch_mentions(keyword, countries, languages)
                mentions.extend(raw)
            except Exception as exc:
                logger.warning("licensed_api_failed", keyword=keyword, error=str(exc))

        logger.info("licensed_api_collected", count=len(mentions))
        return mentions

    async def _fetch_mentions(
        self,
        keyword: str,
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        """
        Adapt this method to the specific provider's request/response schema.
        Talkwalker, Meltwater, and Brandwatch each have slightly different shapes.
        """
        headers = {
            "Authorization": f"Bearer {settings.LICENSED_API_KEY}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{settings.LICENSED_API_BASE_URL}/mentions",
                headers=headers,
                params={
                    "q": keyword,
                    "countries": ",".join(countries),
                    "languages": ",".join(languages),
                    "limit": 100,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        mentions = []
        for item in data.get("results", []):
            text = item.get("content") or item.get("text") or ""
            if not text:
                continue

            published_str = item.get("published_at") or item.get("date")
            published_at = None
            if published_str:
                try:
                    published_at = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                except Exception:
                    published_at = datetime.now(timezone.utc)

            mentions.append(RawMention(
                source_type=self.source_type,
                source_url=item.get("url"),
                country=item.get("country"),
                language=item.get("language"),
                published_at=published_at,
                raw_text=text,
                query_used=keyword,
                engagement_count=item.get("engagement") or item.get("reach"),
                metadata={"provider": settings.LICENSED_API_PROVIDER, "source_name": item.get("source")},
            ))

        return mentions
