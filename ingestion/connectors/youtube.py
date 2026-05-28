from datetime import datetime, timezone
from typing import List

from core.config import settings
from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention
from core.security import pseudonymise_author

logger = get_logger(__name__)

COUNTRY_LANGUAGE_MAP = {
    "BE": ["fr", "nl"],
    "FR": ["fr"],
    "NL": ["nl"],
    "DE": ["de"],
}


class YouTubeConnector(BaseConnector):
    """
    Tier 2 optional connector — YouTube Data API v3.
    Search calls cost 100 quota units; default quota is 10,000 units/day.
    Enabled only when YOUTUBE_API_KEY is configured.
    """
    source_type = "youtube"

    def is_available(self) -> bool:
        return bool(settings.YOUTUBE_API_KEY)

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        if not self.is_available():
            logger.info("youtube_connector_disabled", reason="YOUTUBE_API_KEY not set")
            return []

        from googleapiclient.discovery import build

        youtube = build("youtube", "v3", developerKey=settings.YOUTUBE_API_KEY)
        mentions: List[RawMention] = []
        seen_ids: set = set()

        for keyword in keywords:
            for country in countries:
                try:
                    search_resp = (
                        youtube.search()
                        .list(
                            q=keyword,
                            part="snippet",
                            type="video",
                            regionCode=country,
                            maxResults=10,
                            relevanceLanguage=COUNTRY_LANGUAGE_MAP.get(country, ["fr"])[0],
                            order="date",
                        )
                        .execute()
                    )

                    for item in search_resp.get("items", []):
                        video_id = item["id"].get("videoId")
                        if not video_id or video_id in seen_ids:
                            continue
                        seen_ids.add(video_id)

                        snippet = item.get("snippet", {})
                        text = f"{snippet.get('title', '')} {snippet.get('description', '')}".strip()
                        if not text:
                            continue

                        published_str = snippet.get("publishedAt")
                        published_at = (
                            datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                            if published_str else datetime.now(timezone.utc)
                        )

                        mentions.append(RawMention(
                            source_type=self.source_type,
                            source_url=f"https://www.youtube.com/watch?v={video_id}",
                            country=country,
                            language=snippet.get("defaultAudioLanguage"),
                            published_at=published_at,
                            raw_text=text,
                            query_used=keyword,
                            author_id=pseudonymise_author(snippet.get("channelId", "")) if snippet.get("channelId") else None,
                            engagement_count=None,
                            metadata={"channel_title": snippet.get("channelTitle")},
                        ))

                except Exception as exc:
                    logger.warning("youtube_search_failed", keyword=keyword, country=country, error=str(exc))

        logger.info("youtube_collected", count=len(mentions))
        return mentions
