"""Doctissimo connector — French-language patient forums (popular in BE + FR).

ToS posture: Doctissimo CGU forbid "extraction substantielle" (French sui-generis
DB right). We crawl only PUBLIC forum pages, never the /search/ or /membre/
endpoints (robots-disallowed), throttle aggressively, identify ourselves with a
contact UA, and HMAC-pseudonymise every author handle before storage. Author
identity is never persisted in plaintext.

Lawful basis: legitimate interest for pharmacovigilance signal mining
(GVP Module VI). Must appear in DPIA (`gdpr/dpia.md`) before enabling.
"""
import asyncio
import re
from datetime import datetime, timezone
from typing import List
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from core.config import settings
from core.logging import get_logger
from core.security import pseudonymise_author
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

HEADERS = {
    "User-Agent": (
        "PharmaWatch/1.0 (+https://pharmawatch.eu/bot; "
        "contact=dpo@pharmawatch.eu; EU pharmacovigilance research)"
    ),
    "Accept-Language": "fr-BE,fr;q=0.9",
}

# Forum sections worth crawling per the research findings — drug-relevant only.
FORUM_ROOTS = [
    "https://forum.doctissimo.fr/sante/medicaments/",
    "https://forum.doctissimo.fr/sante/contraception/",
    "https://forum.doctissimo.fr/grossesse-bebe/medicaments-grossesse/",
]

THROTTLE_SECONDS = 6  # ~10 req/min — defensive
MAX_THREADS_PER_KEYWORD = 8


class DoctissimoConnector(BaseConnector):
    source_type = "doctissimo"

    def is_available(self) -> bool:
        # Always available, but require explicit DPIA enable for safety.
        return bool(settings.DPIA_PROCESSING_ENABLED)

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        if "fr" not in languages:
            return []
        if not self.is_available():
            logger.info("doctissimo_disabled", reason="DPIA_PROCESSING_ENABLED is false")
            return []

        mentions: List[RawMention] = []
        seen_urls: set = set()

        async with httpx.AsyncClient(headers=HEADERS, timeout=12.0,
                                     follow_redirects=True) as client:
            for keyword in keywords:
                thread_urls = await self._find_threads(client, keyword)
                for href in thread_urls[:MAX_THREADS_PER_KEYWORD]:
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)
                    await asyncio.sleep(THROTTLE_SECONDS)
                    try:
                        posts = await self._parse_thread(client, href, keyword)
                        mentions.extend(posts)
                    except Exception as exc:
                        logger.warning("doctissimo_thread_failed", url=href,
                                       error=str(exc))

        logger.info("doctissimo_collected", count=len(mentions))
        return mentions

    async def _find_threads(self, client: httpx.AsyncClient, keyword: str) -> List[str]:
        """Find thread URLs by walking the public forum index pages — never the
        /search/ endpoint (robots-disallowed). Match keyword in thread titles."""
        urls: List[str] = []
        kw_lower = keyword.lower()
        for root in FORUM_ROOTS:
            try:
                resp = await client.get(root)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")
                # Doctissimo thread links have `sujet_<id>.htm` in the URL.
                for a in soup.select("a[href*='sujet_']"):
                    href = a.get("href", "")
                    title = a.get_text(" ", strip=True)
                    if not href or kw_lower not in title.lower():
                        continue
                    if not href.startswith("http"):
                        href = "https://forum.doctissimo.fr" + href
                    urls.append(href)
            except Exception as exc:
                logger.warning("doctissimo_root_failed", root=root, error=str(exc))
            await asyncio.sleep(THROTTLE_SECONDS)
        return urls

    async def _parse_thread(self, client: httpx.AsyncClient, url: str,
                            keyword: str) -> List[RawMention]:
        resp = await client.get(url)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        out: List[RawMention] = []

        # Selectors are tolerant — Doctissimo has multiple post layouts.
        posts = soup.select("div.message, div.post-message, article.post, div.messageWrapper")
        for p in posts[:25]:
            body_node = p.select_one(
                ".message-content, .post-content, .messageContent, .contenu"
            )
            if not body_node:
                continue
            text = body_node.get_text(" ", strip=True)
            if not text or len(text) < 40:
                continue

            author_node = p.select_one(".pseudo, a.author, .auteur, .nickname")
            raw_handle = author_node.get_text(strip=True) if author_node else ""
            author_hash = pseudonymise_author(raw_handle, "doctissimo") if raw_handle else None

            time_node = p.select_one("time, .date-post, .datePost")
            published_at = datetime.now(timezone.utc)
            if time_node:
                ts = time_node.get("datetime") or time_node.get_text(strip=True)
                try:
                    if ts and re.match(r"\d{4}-\d{2}-\d{2}", ts):
                        published_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    pass

            out.append(RawMention(
                source_type=self.source_type,
                source_url=url,
                country="BE",  # Belgian + French audience — Doctissimo is FR-wide
                language="fr",
                published_at=published_at,
                raw_text=text[:4000],
                query_used=keyword,
                author_id=author_hash,
                metadata={"forum_section": url.split("doctissimo.fr/")[-1].split("/")[0]},
            ))
        return out