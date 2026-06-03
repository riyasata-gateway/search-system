from datetime import datetime, timezone
from typing import Any, Dict, List

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


def _to_int(value) -> int:
    """YouTube returns counts as strings; some (e.g. likes when hidden) are absent."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class YouTubeQuotaError(RuntimeError):
    """Raised when the YouTube Data API daily quota is exhausted (HTTP 403/429
    'quota' / 'rateLimitExceeded'). Surfaced to the UI as a clear notice instead
    of a silent empty result."""


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "quota" in msg or "ratelimitexceeded" in msg or "dailylimitexceeded" in msg


class YouTubeConnector(BaseConnector):
    """
    Tier 2 optional connector — YouTube Data API v3.

    Two-step fetch:
      1. search.list  (100 quota units/call) → candidate video IDs + snippet
      2. videos.list  (1 quota unit/call, batched ≤50 IDs) → real engagement
         statistics (views / likes / comments) which search.list does NOT return.

    The statistics power both the per-card metrics and the YouTube analytics
    panel on the frontend. Enabled only when YOUTUBE_API_KEY is configured.
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

        # video_id -> partial mention info gathered from search.list
        candidates: Dict[str, Any] = {}
        quota_hit = False

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
                            order="relevance",
                        )
                        .execute()
                    )

                    for item in search_resp.get("items", []):
                        video_id = item["id"].get("videoId")
                        if not video_id or video_id in candidates:
                            continue

                        snippet = item.get("snippet", {})
                        title = snippet.get("title", "") or ""
                        description = snippet.get("description", "") or ""
                        text = f"{title} {description}".strip()
                        if not text:
                            continue

                        published_str = snippet.get("publishedAt")
                        published_at = (
                            datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                            if published_str else datetime.now(timezone.utc)
                        )
                        thumbs = snippet.get("thumbnails", {}) or {}
                        thumb = (
                            (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {})
                            .get("url")
                        )

                        candidates[video_id] = {
                            "title": title,
                            "text": text,
                            "country": country,
                            "language": snippet.get("defaultAudioLanguage"),
                            "published_at": published_at,
                            "query_used": keyword,
                            "channel_id": snippet.get("channelId", ""),
                            "channel_title": snippet.get("channelTitle"),
                            "thumbnail": thumb,
                        }

                except Exception as exc:
                    if _is_quota_error(exc):
                        quota_hit = True
                    logger.warning("youtube_search_failed", keyword=keyword, country=country, error=str(exc))

        if not candidates:
            if quota_hit:
                # No partial data AND we hit the quota wall — tell the caller so
                # the UI can show the real reason rather than a blank result.
                raise YouTubeQuotaError(
                    "YouTube Data API daily quota exhausted — resets ~09:00 CET (midnight US-Pacific)."
                )
            logger.info("youtube_collected", count=0)
            return []

        # ── Step 2: enrich with engagement statistics (batched ≤50 IDs/call) ──
        stats: Dict[str, dict] = {}
        video_ids = list(candidates.keys())
        for start in range(0, len(video_ids), 50):
            batch = video_ids[start:start + 50]
            try:
                videos_resp = (
                    youtube.videos()
                    .list(part="statistics", id=",".join(batch))
                    .execute()
                )
                for v in videos_resp.get("items", []):
                    stats[v["id"]] = v.get("statistics", {}) or {}
            except Exception as exc:
                logger.warning("youtube_stats_failed", error=str(exc), batch_size=len(batch))

        mentions: List[RawMention] = []
        for video_id, info in candidates.items():
            st = stats.get(video_id, {})
            views = _to_int(st.get("viewCount"))
            likes = _to_int(st.get("likeCount"))
            comments = _to_int(st.get("commentCount"))

            mentions.append(RawMention(
                source_type=self.source_type,
                source_url=f"https://www.youtube.com/watch?v={video_id}",
                country=info["country"],
                language=info["language"],
                published_at=info["published_at"],
                raw_text=info["text"],
                query_used=info["query_used"],
                author_id=pseudonymise_author(info["channel_id"]) if info["channel_id"] else None,
                # Engagement = view count; drives both default sort and analytics.
                engagement_count=views,
                metadata={
                    "video_id": video_id,
                    "title": info["title"],
                    "channel_title": info["channel_title"],
                    "thumbnail": info["thumbnail"],
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                },
            ))

        logger.info("youtube_collected", count=len(mentions), enriched=len(stats))
        return mentions
