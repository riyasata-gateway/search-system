"""Dynamic patient-forum search — query-driven, via vetted forums' public APIs.

Earlier this connector tried to crawl hard-coded forum search pages, which broke
the moment a host changed its HTML (the list ended up empty). Instead we now
search **dynamically on the user's query** against forums that expose Discourse's
public, structured `search.json` API. Discourse is the platform behind a large
share of patient/health communities (e.g. patient.info's community), so one code
path covers many forums and never depends on scraping fragile markup.

For each keyword we call `{host}/search.json?q={keyword}` and turn matching
topics/posts into mentions, linking to the public thread. Only forums on the
vetted `DISCOURSE_FORUMS` allow-list are queried (legal/robots posture), and we
keep only the public post text + title — no author handles are stored.

Add a forum by appending to DISCOURSE_FORUMS (must be a public Discourse host).
"""
from datetime import datetime, timezone
from typing import List

import httpx

from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

# Vetted public Discourse health communities. country/language are hints used to
# scope when the caller passes a country/language filter; with no overlap we
# still query (broad research), since patient discussion is cross-border.
DISCOURSE_FORUMS: List[dict] = [
    {"name": "Patient.info Community", "host": "https://community.patient.info",
     "country": "GB", "language": "en"},
]

_HEADERS = {"User-Agent": "PharmaWatch/1.0 (EU pharma research; +https://pharmawatch.eu/bot)"}
_MAX_PER_FORUM_KEYWORD = 20


class ForumScraperConnector(BaseConnector):
    source_type = "forum"

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        kws = [k for k in keywords if k and len(k) >= 2]
        if not kws or not DISCOURSE_FORUMS:
            return []

        mentions: List[RawMention] = []
        seen: set = set()

        async with httpx.AsyncClient(headers=_HEADERS, timeout=15.0, follow_redirects=True) as client:
            for forum in DISCOURSE_FORUMS:
                for keyword in kws:
                    try:
                        resp = await client.get(
                            f"{forum['host']}/search.json", params={"q": keyword}
                        )
                        if resp.status_code != 200:
                            continue
                        data = resp.json()
                    except Exception as exc:
                        logger.warning("forum_search_failed", forum=forum["name"], keyword=keyword, error=str(exc))
                        continue

                    # Build topic_id -> (title, slug) so posts can link to their thread.
                    topics = {t["id"]: t for t in data.get("topics", [])}
                    kept = 0
                    for post in data.get("posts", []):
                        if kept >= _MAX_PER_FORUM_KEYWORD:
                            break
                        tid = post.get("topic_id")
                        topic = topics.get(tid, {})
                        title = topic.get("title", "")
                        blurb = (post.get("blurb") or "").strip()
                        text = f"{title}. {blurb}".strip().strip(".")
                        if len(text) < 50:
                            continue
                        slug = topic.get("slug", "")
                        url = f"{forum['host']}/t/{slug}/{tid}" if slug else f"{forum['host']}/t/{tid}"
                        if url in seen:
                            continue
                        seen.add(url)

                        created = post.get("created_at")
                        published_at = None
                        if created:
                            try:
                                published_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                            except Exception:
                                published_at = None

                        mentions.append(RawMention(
                            source_type=self.source_type,
                            source_url=url,
                            country=forum.get("country"),
                            language=forum.get("language"),
                            published_at=published_at or datetime.now(timezone.utc),
                            raw_text=text[:1500],
                            query_used=keyword,
                            metadata={"forum": forum["name"]},
                        ))
                        kept += 1

        logger.info("forum_search_collected", count=len(mentions))
        return mentions
