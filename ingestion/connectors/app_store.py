"""Apple App Store customer reviews — ToS-safe patient-review source.

Apple exposes review feeds as official RSS: no key, no scraping, no ToS
violation. The endpoint shape is:

  https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/json

Pharma-relevant apps are seeded per country in `EU_HEALTH_APP_IDS`. The
connector matches per keyword against title+content of each review and
returns hits as RawMention rows. Engagement_count carries the star rating
so downstream scoring can weight high-volume positive/negative apps.

The seed list focuses on apps that explicitly discuss medication, symptoms,
or pharmacy operations — this is the surface where patient reviews live
that are most likely to mention OTC brands, side effects, or shortages.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List

import httpx

from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

# Seed app IDs per country. Real deployments expand this via Setup → Apps.
# IDs below are public iTunes app identifiers and are interchangeable.
EU_HEALTH_APP_IDS = [
    {"country": "FR", "app_id": "1037126344", "name": "Doctolib", "language": "fr"},
    {"country": "BE", "app_id": "1037126344", "name": "Doctolib", "language": "fr"},
    {"country": "FR", "app_id": "1163448914", "name": "Medadom",  "language": "fr"},
    {"country": "BE", "app_id": "1517783697", "name": "MaSantéBE", "language": "nl"},
    {"country": "NL", "app_id": "1108776591", "name": "Apotheek.nl", "language": "nl"},
    {"country": "DE", "app_id": "1138105526", "name": "DocMorris", "language": "de"},
    {"country": "GB", "app_id": "1056943981", "name": "Pharmacy2U", "language": "en"},
]

_HEADERS = {"User-Agent": "PharmaWatch/1.0"}


class AppStoreReviewsConnector(BaseConnector):
    source_type = "app_store"

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        keywords_lower = [k.lower() for k in keywords if k]
        if not keywords_lower:
            return []

        mentions: List[RawMention] = []
        seen_review_ids: set = set()

        async with httpx.AsyncClient(timeout=8.0, headers=_HEADERS) as client:
            for app in EU_HEALTH_APP_IDS:
                if countries and app["country"] not in countries:
                    continue
                if languages and app["language"] not in languages:
                    continue
                url = (
                    f"https://itunes.apple.com/{app['country'].lower()}"
                    f"/rss/customerreviews/id={app['app_id']}/sortBy=mostRecent/json"
                )
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    feed = resp.json().get("feed", {})
                    entries = feed.get("entry", []) or []
                    # Apple wraps the app metadata as entry[0] when present.
                    if entries and "im:name" in entries[0] and "im:rating" not in entries[0]:
                        entries = entries[1:]
                except Exception as exc:
                    logger.warning("app_store_fetch_failed", app=app["name"], error=str(exc))
                    continue

                for entry in entries:
                    rid = (entry.get("id") or {}).get("label")
                    if not rid or rid in seen_review_ids:
                        continue
                    title = (entry.get("title") or {}).get("label", "") or ""
                    content = (entry.get("content") or {}).get("label", "") or ""
                    body = f"{title}. {content}".strip().rstrip(".")
                    body_lower = body.lower()
                    matched = next((k for k in keywords_lower if k in body_lower), None)
                    if not matched:
                        continue
                    seen_review_ids.add(rid)

                    rating_raw = (entry.get("im:rating") or {}).get("label")
                    try:
                        rating = int(rating_raw) if rating_raw else None
                    except ValueError:
                        rating = None

                    updated = (entry.get("updated") or {}).get("label")
                    published_at = None
                    if updated:
                        try:
                            published_at = parsedate_to_datetime(updated)
                        except Exception:
                            try:
                                published_at = datetime.fromisoformat(
                                    updated.replace("Z", "+00:00")
                                )
                            except Exception:
                                published_at = None
                    if published_at is None:
                        published_at = datetime.now(timezone.utc)

                    review_url = ((entry.get("link") or {}).get("attributes") or {}).get(
                        "href"
                    ) or f"https://apps.apple.com/{app['country'].lower()}/app/id{app['app_id']}"

                    mentions.append(
                        RawMention(
                            source_type=self.source_type,
                            source_url=review_url,
                            country=app["country"],
                            language=app["language"],
                            published_at=published_at,
                            raw_text=body[:1200],
                            query_used=matched,
                            engagement_count=rating,  # star rating is the "engagement" signal
                            metadata={
                                "app_id": app["app_id"],
                                "app_name": app["name"],
                                "review_id": rid,
                                "rating": rating,
                            },
                        )
                    )

        logger.info("app_store_collected", count=len(mentions))
        return mentions
