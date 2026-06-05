"""EudraVigilance / adrreports.eu connector — EU-native pharmacovigilance.

Replaces the US openFDA FAERS feed for EU-market adverse-event signal.
Data source: adrreports.eu (EMA's public ADR portal, refreshed weekly Monday).

Two layers:
  1. Substance index page (static HTML, free to fetch) — gives us the EV
     substance code + landing-page URL per active substance.
  2. SAP BusinessObjects iframe inside the substance landing page renders the
     case counts + line listings. Programmatic XLSX export requires a headless
     browser (Playwright / Selenium) because the BO iframe is JS-driven.

This connector implements layer (1) reliably with httpx + BeautifulSoup and
exposes the substance landing URL as a `RawMention` per matched keyword. That
gives the platform a usable EU-native source today; the deeper line-listing
extraction is wired as `_extract_xlsx_via_playwright()` stub for the next
iteration (Playwright not yet a dep — add `playwright` to requirements.txt to
enable).

GDPR: EMA pre-pseudonymises all line listings. Treat aggregate counts as
non-personal; treat line-listing rows as Art. 9 special-category data and
restrict to authenticated pharmacist/lab roles.
"""
import asyncio
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

ADRREPORTS_BASE = "https://www.adrreports.eu"
SUBSTANCE_INDEX_URL = f"{ADRREPORTS_BASE}/en/search_subst.html"

HEADERS = {
    "User-Agent": (
        "PharmaWatch/1.0 (+https://pharmawatch.eu/bot; "
        "contact=pharmacovigilance@pharmawatch.eu; EU pharmacovigilance research)"
    ),
    "Accept-Language": "en,fr;q=0.7",
}

# adrreports.eu is alphabetised; A.html, B.html, ... Z.html
_ALPHABET = "abcdefghijklmnopqrstuvwxyz"


class EudraVigilanceConnector(BaseConnector):
    source_type = "eudravigilance"

    def is_available(self) -> bool:
        # No auth — public portal. We require nothing in .env.
        return True

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        # We don't filter by country here — EudraVigilance is EEA-wide and the
        # Belgian + French signal is already inside the substance-level totals.
        # The granular BE-only breakdown lives on the line-listing XLSX which
        # needs Playwright (see _extract_xlsx_via_playwright stub).
        mentions: List[RawMention] = []
        seen: set = set()

        async with httpx.AsyncClient(headers=HEADERS, timeout=15.0,
                                     follow_redirects=True) as client:
            for keyword in keywords:
                hits = await self._find_substance_pages(client, keyword)
                for substance_name, landing_url in hits:
                    if landing_url in seen:
                        continue
                    seen.add(landing_url)
                    mentions.append(RawMention(
                        source_type=self.source_type,
                        source_url=landing_url,
                        country="EU",  # EEA-wide aggregate
                        language="en",
                        published_at=datetime.now(timezone.utc),
                        raw_text=(
                            f"EudraVigilance ADR report landing page for "
                            f"active substance '{substance_name}'. "
                            f"Public EEA pharmacovigilance data (weekly-refreshed). "
                            f"Source: {landing_url}"
                        ),
                        query_used=keyword,
                        metadata={"substance": substance_name},
                    ))
                await asyncio.sleep(2.0)  # be polite to EMA infra

        logger.info("eudravigilance_collected", count=len(mentions))
        return mentions

    async def _find_substance_pages(self, client: httpx.AsyncClient,
                                    keyword: str) -> List[tuple]:
        """Scan the per-letter index page for the keyword's first letter and
        return (substance_name, landing_url) tuples whose name contains the
        keyword (case-insensitive substring match)."""
        kw = keyword.strip().lower()
        if not kw:
            return []
        letter = kw[0] if kw[0] in _ALPHABET else None
        if not letter:
            return []
        index_url = f"{ADRREPORTS_BASE}/en/medicines/{letter.upper()}.html"
        try:
            resp = await client.get(index_url)
            if resp.status_code != 200:
                # Fall back to the legacy substance/<letter>.html path
                alt = f"{ADRREPORTS_BASE}/tables/substance/{letter}.html"
                resp = await client.get(alt)
                if resp.status_code != 200:
                    return []
        except Exception as exc:
            logger.warning("eudravigilance_index_failed", letter=letter,
                           error=str(exc))
            return []

        out: List[tuple] = []
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.select("a[href]"):
            name = a.get_text(" ", strip=True)
            href = a.get("href", "")
            if not name or kw not in name.lower():
                continue
            if not href.startswith("http"):
                href = f"{ADRREPORTS_BASE}{href}" if href.startswith("/") else f"{ADRREPORTS_BASE}/en/{href}"
            out.append((name, href))
            if len(out) >= 10:
                break
        return out

    async def _extract_xlsx_via_playwright(self, landing_url: str) -> Optional[bytes]:
        """STUB — implement once `playwright` is added to requirements.txt.

        Implementation outline:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(user_agent=HEADERS["User-Agent"])
                await page.goto(landing_url, wait_until="networkidle")
                # Find iframe → click "Line Listing" tab → click export → XLSX
                async with page.expect_download() as dl_info:
                    await page.click('button[title="Export"]')
                    await page.click('text="Excel"')
                download = await dl_info.value
                content = await download.path()
                with open(content, "rb") as f:
                    return f.read()
        """
        return None