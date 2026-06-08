"""Doctissimo connector — French-language patient forums (popular in BE + FR).

ToS posture: Doctissimo CGU forbid "extraction substantielle" (French sui-generis
DB right). We crawl only PUBLIC forum listing/thread pages, never the robots-
disallowed `/recherche/`, `/search*`, `/membre/`, `/user/` endpoints; throttle
aggressively; identify ourselves with a contact UA; and HMAC-pseudonymise every
author handle before storage. Author identity is never persisted in plaintext.

Lawful basis: legitimate interest for pharmacovigilance signal mining
(GVP Module VI). Must appear in DPIA (`gdpr/dpia.md`) before enabling.

Site structure (verified): the old `sante/medicaments/` directory URLs now 404 and
the forum's own search is JS-only/robots-blocked. The working path is the public
listing walk:
  category index  → `…/medicaments/liste_categorie.htm` (+ `…/nutrition/…`)
                    → sub-forum links `a[href*='liste_sujet']`
  thread listing  → `…/<subforum>/liste_sujet-N.htm` → thread links `a[href*='sujet_']`
  thread page     → posts in `div.md-post` (body `.md-post__content-body`,
                    author `.md-post__header__user`, date `.md-post__header__info`,
                    French `DD/MM/YYYY à HHhMM`).
We build the recent-thread title index ONCE per run (cached on the instance) and
match keywords against it in memory, so a batch over many brands is cheap.
"""
import asyncio
import re
import unicodedata
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from core.config import settings
from core.logging import get_logger
from core.security import pseudonymise_author
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0 "
        "(+https://pharmawatch.eu/bot; contact=dpo@pharmawatch.eu)"
    ),
    "Accept-Language": "fr-BE,fr;q=0.9",
}

CATEGORY_INDEXES = [
    "https://forum.doctissimo.fr/medicaments/liste_categorie.htm",
    "https://forum.doctissimo.fr/nutrition/liste_categorie.htm",
]
BASE = "https://forum.doctissimo.fr"
THROTTLE_SECONDS = 2.0
MAX_SUBFORUMS = 30
MAX_THREADS_PER_KEYWORD = 6


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))
    return s.lower()


def _sujet_id(href: str) -> Optional[str]:
    m = re.search(r"sujet_(\d+)", href or "")
    return m.group(1) if m else None


class DoctissimoConnector(BaseConnector):
    source_type = "doctissimo"

    def __init__(self):
        # (title_norm, title, url) for recent threads — built once, reused.
        self._index: Optional[List[Tuple[str, str, str]]] = None

    def is_available(self) -> bool:
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
        async with httpx.AsyncClient(headers=HEADERS, timeout=15.0,
                                     follow_redirects=True) as client:
            index = await self._get_index(client)
            for keyword in keywords:
                kwn = _norm(keyword)
                if len(kwn) < 3:
                    continue
                matches = [(t, u) for (tn, t, u) in index if kwn in tn][:MAX_THREADS_PER_KEYWORD]
                for _title, href in matches:
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)
                    await asyncio.sleep(THROTTLE_SECONDS)
                    try:
                        mentions.extend(await self._parse_thread(client, href, keyword))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("doctissimo_thread_failed", url=href, error=str(exc))

        logger.info("doctissimo_collected", count=len(mentions))
        return mentions

    async def _get_index(self, client: httpx.AsyncClient) -> List[Tuple[str, str, str]]:
        if self._index is not None:
            return self._index
        self._index = []
        try:
            # 1) discover sub-forum listing pages from the category indexes
            subforums: List[str] = []
            for cat in CATEGORY_INDEXES:
                try:
                    r = await client.get(cat)
                    if r.status_code != 200:
                        continue
                    soup = BeautifulSoup(r.text, "html.parser")
                    for a in soup.select("a[href*='liste_sujet']"):
                        href = a.get("href", "")
                        if not href:
                            continue
                        url = href if href.startswith("http") else BASE + href
                        if url not in subforums:
                            subforums.append(url)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("doctissimo_category_failed", cat=cat, error=str(exc))
                await asyncio.sleep(THROTTLE_SECONDS)

            # 2) collect recent thread titles from each sub-forum's first listing page
            seen_ids: set = set()
            for sf in subforums[:MAX_SUBFORUMS]:
                try:
                    r = await client.get(sf)
                    if r.status_code != 200:
                        continue
                    soup = BeautifulSoup(r.text, "html.parser")
                    for a in soup.select("a[href*='sujet_']"):
                        href = a.get("href", "")
                        sid = _sujet_id(href)
                        title = a.get_text(" ", strip=True)
                        if not sid or sid in seen_ids or len(title) < 4:
                            continue
                        seen_ids.add(sid)
                        url = href if href.startswith("http") else BASE + href
                        self._index.append((_norm(title), title, url))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("doctissimo_subforum_failed", sf=sf, error=str(exc))
                await asyncio.sleep(THROTTLE_SECONDS)
            logger.info("doctissimo_index_built", threads=len(self._index), subforums=len(subforums))
        except Exception as exc:  # noqa: BLE001
            logger.warning("doctissimo_index_error", error=str(exc))
        return self._index

    async def _parse_thread(self, client: httpx.AsyncClient, url: str,
                            keyword: str) -> List[RawMention]:
        resp = await client.get(url)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        out: List[RawMention] = []
        for p in soup.select("div.md-post")[:25]:
            body_node = p.select_one(".md-post__content-body")
            if not body_node:
                continue
            text = body_node.get_text(" ", strip=True)
            if not text or len(text) < 40:
                continue
            author_node = p.select_one(".md-post__header__user")
            raw_handle = author_node.get_text(strip=True) if author_node else ""
            author_hash = pseudonymise_author(raw_handle, "doctissimo") if raw_handle else None

            published_at = datetime.now(timezone.utc)
            date_node = p.select_one(".md-post__header__info")
            if date_node:
                m = re.search(r"(\d{2})/(\d{2})/(\d{4})(?:\s+à\s+(\d{2})h(\d{2}))?",
                              date_node.get_text(" ", strip=True))
                if m:
                    d, mo, y, hh, mm = m.groups()
                    try:
                        published_at = datetime(int(y), int(mo), int(d),
                                                int(hh or 0), int(mm or 0), tzinfo=timezone.utc)
                    except ValueError:
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
                metadata={"forum_section": url.replace(BASE + "/", "").split("/")[0]},
            ))
        return out