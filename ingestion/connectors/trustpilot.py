"""Trustpilot connector — Belgian pharmacy customer reviews (via headless browser).

Trustpilot blocks plain HTTP from datacenter IPs with an AWS-WAF interstitial,
but a real browser (Playwright) passes it and the page embeds every review as
structured JSON in `#__NEXT_DATA__` (`props.pageProps.reviews`: rating, title,
text, publishedDate, consumer, language). We crawl the Belgian online-pharmacy
domains — by far the largest free pool of FR/NL consumer reviews that name the
products and brands we track.

These are *service* reviews, so attribution is by CONTENT: a review is linked to
a brand only when it names that brand (the downstream word-boundary gate), never
to the pharmacy. The crawl is built once per run and cached on the instance, so a
per-brand batch just filters the cached reviews by the brand's trade-name terms.

ToS/GDPR: logged-out public pages only; throttled; author handles HMAC-
pseudonymised before storage; record in `gdpr/dpia.md` before enabling.
"""
import asyncio
from typing import List, Optional

from core.logging import get_logger
from core.security import pseudonymise_author
from ingestion.browser_fetch import BrowserSession, playwright_available
from ingestion.connectors.base import BaseConnector, RawMention
from processing.brand_match import text_mentions_brand

logger = get_logger(__name__)

# Belgian online-pharmacy Trustpilot profiles (FR/NL consumer reviews).
PHARMACY_DOMAINS = [
    "www.newpharma.be", "www.medi-market.be", "www.viata.be", "www.24pharma.be",
    "www.pharmasimple.com", "www.lloydspharma.be", "www.kruidvat.be",
]
REVIEW_URL = "https://www.trustpilot.com/review/{domain}?page={page}"
MAX_PAGES_PER_DOMAIN = 30   # was 10 (~200 reviews) — too few; missed brand mentions in older reviews
THROTTLE_SECONDS = 1.5


class TrustpilotConnector(BaseConnector):
    source_type = "trustpilot"

    def __init__(self):
        self._reviews: Optional[List[dict]] = None  # cached normalised reviews

    def is_available(self) -> bool:
        return playwright_available()

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        if not self.is_available():
            logger.info("trustpilot_disabled", reason="playwright/chromium not available")
            return []
        reviews = await self._get_reviews()

        out: List[RawMention] = []
        for r in reviews:
            if languages and r["language"] and r["language"] not in languages:
                continue
            # Attribution by content: the review must NAME one of the brand terms.
            if not text_mentions_brand(r["text"], keywords):
                continue
            out.append(RawMention(
                source_type=self.source_type,
                source_url=r["url"],
                country="BE",
                language=r["language"] or None,
                published_at=r["published_at"],
                raw_text=r["text"][:2000],
                query_used=keywords[0] if keywords else "",
                author_id=r["author_hash"],
                engagement_count=r["rating"],   # star rating is the engagement signal
                metadata={"pharmacy": r["domain"], "rating": r["rating"]},
            ))
        logger.info("trustpilot_collected", count=len(out))
        return out

    async def _get_reviews(self) -> List[dict]:
        if self._reviews is not None:
            return self._reviews
        self._reviews: List[dict] = []
        from datetime import datetime, timezone

        # WAF challenge is JS that redirects to the real page; don't block assets,
        # and wait for review cards ("article") before reading the data blob.
        async with BrowserSession(locale="fr-BE", block_assets=False) as bs:
            for domain in PHARMACY_DOMAINS:
                for page in range(1, MAX_PAGES_PER_DOMAIN + 1):
                    data = await bs.next_data(
                        REVIEW_URL.format(domain=domain, page=page),
                        wait_selector="article")
                    await asyncio.sleep(THROTTLE_SECONDS)
                    if not data:
                        break
                    reviews = (data.get("props", {}).get("pageProps", {})
                               .get("reviews", []) or [])
                    if not reviews:
                        break
                    for r in reviews:
                        title = (r.get("title") or "").strip()
                        body = (r.get("text") or "").strip()
                        text = f"{title}. {body}".strip(". ").strip()
                        if len(text) < 20:
                            continue
                        pub = (r.get("dates") or {}).get("publishedDate")
                        published_at = None
                        if pub:
                            try:
                                published_at = datetime.fromisoformat(
                                    pub.replace("Z", "+00:00"))
                            except Exception:
                                published_at = None
                        handle = (r.get("consumer") or {}).get("displayName") or ""
                        rid = r.get("id") or ""
                        self._reviews.append({
                            "text": text,
                            "language": (r.get("language") or "").lower() or None,
                            "rating": r.get("rating"),
                            "published_at": published_at,
                            "author_hash": pseudonymise_author(handle, "trustpilot") if handle else None,
                            "domain": domain,
                            "url": f"https://www.trustpilot.com/reviews/{rid}" if rid
                                   else f"https://www.trustpilot.com/review/{domain}",
                        })
        logger.info("trustpilot_index_built", reviews=len(self._reviews))
        return self._reviews