from datetime import datetime, timezone
from typing import List

from core.config import settings
from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention
from core.security import pseudonymise_author

logger = get_logger(__name__)

EU_HEALTH_SUBREDDITS = [
    "pharmacie",
    "belgium",
    "france",
    "Netherlands",
    "germany",
    "health",
    "medical",
    "pharmacy",
    "AskDocs",
    "medication",
]


class RedditConnector(BaseConnector):
    source_type = "reddit"

    def __init__(self):
        import praw
        self._reddit = praw.Reddit(
            client_id=settings.REDDIT_CLIENT_ID,
            client_secret=settings.REDDIT_CLIENT_SECRET,
            user_agent=settings.REDDIT_USER_AGENT,
        )

    def is_available(self) -> bool:
        return bool(settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET)

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        if not self.is_available():
            logger.warning("reddit_connector_unavailable", reason="Missing credentials")
            return []

        mentions: List[RawMention] = []
        seen_ids = set()

        for keyword in keywords:
            for subreddit_name in EU_HEALTH_SUBREDDITS:
                try:
                    subreddit = self._reddit.subreddit(subreddit_name)
                    for submission in subreddit.search(keyword, limit=25, sort="new"):
                        if submission.id in seen_ids:
                            continue
                        seen_ids.add(submission.id)

                        text = f"{submission.title}\n{submission.selftext}".strip()
                        if not text:
                            continue

                        mentions.append(RawMention(
                            source_type=self.source_type,
                            source_url=f"https://reddit.com{submission.permalink}",
                            country=None,
                            language=None,
                            published_at=datetime.fromtimestamp(submission.created_utc, tz=timezone.utc),
                            raw_text=text,
                            query_used=keyword,
                            author_id=pseudonymise_author(str(submission.author)) if submission.author else None,
                            engagement_count=submission.score,
                            metadata={
                                "subreddit": subreddit_name,
                                "num_comments": submission.num_comments,
                            },
                        ))

                        for comment in submission.comments[:10]:
                            if hasattr(comment, "body") and comment.body not in ("[deleted]", "[removed]"):
                                mentions.append(RawMention(
                                    source_type=self.source_type,
                                    source_url=f"https://reddit.com{submission.permalink}",
                                    country=None,
                                    language=None,
                                    published_at=datetime.fromtimestamp(comment.created_utc, tz=timezone.utc),
                                    raw_text=comment.body,
                                    query_used=keyword,
                                    author_id=pseudonymise_author(str(comment.author)) if comment.author else None,
                                    engagement_count=comment.score,
                                    metadata={"subreddit": subreddit_name, "type": "comment"},
                                ))

                except Exception as exc:
                    logger.warning("reddit_subreddit_failed", subreddit=subreddit_name, keyword=keyword, error=str(exc))

        logger.info("reddit_collected", count=len(mentions))
        return mentions
