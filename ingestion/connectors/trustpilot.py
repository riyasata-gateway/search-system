"""Trustpilot reviews — patient/consumer review source via their public API.

Requires `TRUSTPILOT_API_KEY` (free read-only key from Trustpilot's Business
API). Without a key, `is_available()` returns False and the connector is
skipped — the rest of the search continues to work.

Strategy: search Trustpilot's business directory for businesses matching
each keyword (e.g. a pharmacy chain or DTC pharma brand), then pull their
most-recent reviews. Star rating becomes `engagement_count`; review title
+ body becomes raw_text.
"""
from datetime import datetime
from typing import List

import httpx

from core.config import settings
from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

TP_API_BASE = "https://api.trustpilot.com/v1"
_HEADERS_TEMPLATE = {"User-Agent": "PharmaWatch/1.0", "Accept": "application/json"}


class TrustpilotConnector(BaseConnector):
    source_type = "trustpilot"

    def is_available(self) -> bool:
        return bool(settings.TRUSTPILOT_API_KEY)

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        if not self.is_available():
            logger.info("trustpilot_skipped", reason="TRUSTPILOT_API_KEY not set")
            return []

        headers = dict(_HEADERS_TEMPLATE)
        headers["apikey"] = settings.TRUSTPILOT_API_KEY  # Trustpilot uses lowercased header

        mentions: List[RawMention] = []
        seen_review_ids: set = set()

        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            for keyword in keywords:
                try:
                    search_resp = await client.get(
                        f"{TP_API_BASE}/business-units/search",
                        params={"query": keyword, "perPage": 5},
                    )
                    if search_resp.status_code != 200:
                        continue
                    businesses = search_resp.json().get("businessUnits", []) or []
                except Exception as exc:
                    logger.warning("trustpilot_search_failed", keyword=keyword, error=str(exc))
                    continue

                for biz in businesses:
                    biz_id = biz.get("id")
                    biz_country = (biz.get("country") or "").upper() or None
                    if countries and biz_country and biz_country not in countries:
                        continue
                    try:
                        rev_resp = await client.get(
                            f"{TP_API_BASE}/business-units/{biz_id}/reviews",
                            params={"perPage": 10, "orderBy": "createdat.desc"},
                        )
                        if rev_resp.status_code != 200:
                            continue
                        reviews = rev_resp.json().get("reviews", []) or []
                    except Exception as exc:
                        logger.warning("trustpilot_reviews_failed",
                                       business=biz.get("displayName"), error=str(exc))
                        continue

                    for r in reviews:
                        rid = r.get("id")
                        if not rid or rid in seen_review_ids:
                            continue
                        seen_review_ids.add(rid)
                        title = r.get("title") or ""
                        text = r.get("text") or ""
                        body = f"{title}. {text}".strip().rstrip(".")
                        if len(body) < 30:
                            continue
                        stars = r.get("stars")
                        created = r.get("createdAt")
                        published_at = None
                        if created:
                            try:
                                published_at = datetime.fromisoformat(
                                    created.replace("Z", "+00:00")
                                )
                            except Exception:
                                published_at = None
                        lang = (r.get("language") or "").lower() or None
                        if languages and lang and lang not in languages:
                            # Soft filter — keep it if there's no other source
                            continue

                        mentions.append(
                            RawMention(
                                source_type=self.source_type,
                                source_url=(r.get("links", [{}])[0] or {}).get("href")
                                          or f"https://trustpilot.com/review/{biz.get('displayName', '')}",
                                country=biz_country,
                                language=lang,
                                published_at=published_at,
                                raw_text=body[:1500],
                                query_used=keyword,
                                engagement_count=stars,
                                metadata={
                                    "business_id": biz_id,
                                    "business_name": biz.get("displayName"),
                                    "review_id": rid,
                                    "stars": stars,
                                },
                            )
                        )

        logger.info("trustpilot_collected", count=len(mentions))
        return mentions
