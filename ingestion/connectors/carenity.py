"""Carenity connector — French drug-level patient reviews/testimonials.

Carenity is a large FR patient community with per-medication "Avis et témoignages"
pages. These are genuine drug-level patient sentiment (efficacy, side effects,
adherence) — high value for the medicine brands we track, and FR is a Belgian
official language.

ToS / lawful basis: same posture as `doctissimo.py`. We crawl only PUBLIC
medication review pages, throttle, identify ourselves, HMAC-pseudonymise every
author handle, and gate on DPIA. French sui-generis DB right → no substantial
extraction (bounded page/comment caps).

Site structure (verified 2026-06):
  index   → `/donner-mon-avis/index-medicaments` + `/donner-mon-avis/medicaments`
            → drug links `a[href*='/donner-mon-avis/medicaments/<slug>-<id>']`
  drug    → `h1` ("Tramadol (TRAMADOL CHLORHYDRATE) : Avis…")
            comments in `.box-commentaire-public`:
              author `.meta-primary`, date `.meta-seconday` ("le DD/MM/YYYY"),
              body `.message`.

Attribution: a comment is about the DRUG of its page, so we match brand
trade-name terms (the connector's `keywords`) against the drug name and prepend
that drug name to the stored text — the downstream brand-attribution gate then
links it to the brand by the named drug, exactly like a product review.
"""
import asyncio
import re
import string
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from core.config import settings
from core.logging import get_logger
from core.security import pseudonymise_author
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

BASE = "https://www.carenity.com"
# Full A–Z medication directory: one page per letter lists that letter's drugs
# (verified — /A → abasaglar…, /T → tachosil…, /V → vaccins…; IDs run past 3300).
INDEX_LETTER_URL = BASE + "/donner-mon-avis/index-medicaments/{letter}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0 "
        "(+https://pharmawatch.eu/bot; contact=dpo@pharmawatch.eu)"
    ),
    "Accept-Language": "fr-BE,fr;q=0.9",
}
THROTTLE_SECONDS = 2.0
MAX_DRUGS_PER_RUN = 40
MAX_COMMENTS_PER_DRUG = 40
MAX_INDEX_PAGES_PER_LETTER = 40  # safety cap; busiest letters run ~20 pages
_SLUG_RE = re.compile(r"/donner-mon-avis/medicaments/([a-z0-9-]+-\d+)")
_PAGE_RE = re.compile(r"index-medicaments/[A-Z]\?page=(\d+)")


def _fold(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))
    return s.lower()


def _drug_name_from_slug(slug: str) -> str:
    # 'tramadol-chlorhydrate-3198' → 'tramadol chlorhydrate'
    return re.sub(r"-\d+$", "", slug).replace("-", " ")


class CarenityConnector(BaseConnector):
    source_type = "carenity"

    def __init__(self):
        self._index: Optional[Dict[str, str]] = None  # drug_name_folded -> url

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
            logger.info("carenity_disabled", reason="DPIA_PROCESSING_ENABLED is false")
            return []

        terms = [_fold(k) for k in keywords if k and len(k) >= 4]
        if not terms:
            return []

        mentions: List[RawMention] = []
        async with httpx.AsyncClient(headers=HEADERS, timeout=15.0,
                                     follow_redirects=True) as client:
            index = await self._get_index(client)
            # Match brand terms against drug names; fetch each matched drug once.
            matched_urls: Dict[str, str] = {}
            for name_folded, url in index.items():
                if url in matched_urls.values():
                    continue
                if any(t in name_folded for t in terms):
                    matched_urls[name_folded] = url
                if len(matched_urls) >= MAX_DRUGS_PER_RUN:
                    break
            for url in matched_urls.values():
                await asyncio.sleep(THROTTLE_SECONDS)
                try:
                    mentions.extend(await self._parse_drug(client, url, keywords[0]))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("carenity_drug_failed", url=url, error=str(exc))

        logger.info("carenity_collected", count=len(mentions))
        return mentions

    async def _get_index(self, client: httpx.AsyncClient) -> Dict[str, str]:
        if self._index is not None:
            return self._index
        self._index = {}
        for letter in string.ascii_uppercase:
            base_url = INDEX_LETTER_URL.format(letter=letter)
            try:
                r = await client.get(base_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("carenity_index_failed", letter=letter, error=str(exc))
                await asyncio.sleep(THROTTLE_SECONDS)
                continue
            if r.status_code != 200:
                await asyncio.sleep(THROTTLE_SECONDS)
                continue
            self._add_slugs(r.text)
            # Each letter is paginated (?page=N); follow to the last page.
            pages = [int(p) for p in _PAGE_RE.findall(r.text)]
            last = min(max(pages) if pages else 1, MAX_INDEX_PAGES_PER_LETTER)
            await asyncio.sleep(THROTTLE_SECONDS)
            for page in range(2, last + 1):
                try:
                    rp = await client.get(f"{base_url}?page={page}")
                    if rp.status_code == 200:
                        self._add_slugs(rp.text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("carenity_page_failed", letter=letter, page=page, error=str(exc))
                await asyncio.sleep(THROTTLE_SECONDS)
        logger.info("carenity_index_built", drugs=len(self._index))
        return self._index

    def _add_slugs(self, html: str) -> None:
        for slug in set(_SLUG_RE.findall(html)):
            url = f"{BASE}/donner-mon-avis/medicaments/{slug}"
            self._index[_fold(_drug_name_from_slug(slug))] = url

    async def _parse_drug(self, client: httpx.AsyncClient, url: str,
                          keyword: str) -> List[RawMention]:
        resp = await client.get(url)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        h1 = soup.find("h1")
        drug = (h1.get_text(" ", strip=True).split(":")[0].strip() if h1 else keyword)

        out: List[RawMention] = []
        for block in soup.select(".box-commentaire-public")[:MAX_COMMENTS_PER_DRUG]:
            body_node = block.select_one(".message")
            if not body_node:
                continue
            text = body_node.get_text(" ", strip=True)
            if not text or len(text) < 40:
                continue
            author_node = block.select_one(".meta-primary")
            raw_handle = author_node.get_text(strip=True) if author_node else ""
            author_hash = pseudonymise_author(raw_handle, "carenity") if raw_handle else None

            published_at = None
            date_node = block.select_one(".meta-seconday")
            if date_node:
                m = re.search(r"(\d{2})/(\d{2})/(\d{4})", date_node.get_text(" ", strip=True))
                if m:
                    d, mo, y = m.groups()
                    try:
                        published_at = datetime(int(y), int(mo), int(d), tzinfo=timezone.utc)
                    except ValueError:
                        pass

            # Prepend the drug name so brand attribution links by the named drug.
            stored = f"{drug}: {text}"
            out.append(RawMention(
                source_type=self.source_type,
                source_url=url,
                country="BE",          # FR-language, Belgian + French patient audience
                language="fr",
                published_at=published_at,
                raw_text=stored[:4000],
                query_used=keyword,
                author_id=author_hash,
                metadata={"drug": drug},
            ))
        return out