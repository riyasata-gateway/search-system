"""Belgian HCP discovery connector — public registers only.

Implements the PUBLIC_OPEN tier from the HCP research:
  1. FAMHP public pharmacy list (canonical pharmacy directory for BE)
  2. INAMI/RIZIV "Find a healthcare professional" — name + NIHII + specialty
  3. Doctena BE A-Z directory — opt-in HCP profiles

NOT IMPLEMENTED (require contract / paid licence):
  - IQVIA OneKey — commercial HCP master file (only source for per-HCP Rx)
  - LinkedIn Sales Navigator — manual prospecting only; scraping violates ToS
  - FarmaFlux PCDH — restricted to federal partners

GDPR posture: HCP registers are public professional data. Lawful basis =
legitimate interest. Must publish HCP-facing privacy notice and honour Art. 21
objection before activating. APD/GBA (Belgian DPA) actively enforces on B2B
HCP databases — keep crawls polite + identifiable.
"""
import asyncio
from datetime import datetime, timezone
from typing import List
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

HEADERS = {
    "User-Agent": (
        "PharmaWatch/1.0 (+https://pharmawatch.eu/bot; "
        "contact=dpo@pharmawatch.eu; Belgian HCP register lookup)"
    ),
    "Accept-Language": "fr-BE,fr;q=0.9,nl;q=0.7,en;q=0.5",
}

FAMHP_PHARMACY_LIST = (
    "https://www.famhp.be/en/human_use/medicines/medicines/"
    "distribution_delivery/pharmacy_public"
)

# INAMI/RIZIV public "silverpages" — official HCP register. The /Home form
# posts the search to /Home/SearchHcw/ and renders results as HTML.
INAMI_BASE = "https://webappsa.riziv-inami.fgov.be/silverpages"
INAMI_LOOKUP = f"{INAMI_BASE}/Home/SearchHcw/"

# Doctena BE A-Z medical/paramedical directory
DOCTENA_DIRECTORY = "https://www.doctena.be/en/medical-and-paramedical-directory/{letter}"

THROTTLE = 4.0  # seconds between HTTP calls — APD-friendly


class BelgiumHCPConnector(BaseConnector):
    source_type = "belgium_hcp"

    def is_available(self) -> bool:
        return True  # purely public registers

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        """`keywords` here mean HCP names, specialties, or pharmacy names.
        Not drug names. Caller decides what to look up."""
        if "BE" not in countries:
            return []

        mentions: List[RawMention] = []
        async with httpx.AsyncClient(headers=HEADERS, timeout=12.0,
                                     follow_redirects=True) as client:
            # FAMHP pharmacy list is a fixed page — fetch once, filter by all keywords.
            pharmacy_hits = await self._fetch_famhp_pharmacies(client, keywords)
            mentions.extend(pharmacy_hits)
            await asyncio.sleep(THROTTLE)

            for keyword in keywords:
                inami = await self._fetch_inami(client, keyword)
                mentions.extend(inami)
                await asyncio.sleep(THROTTLE)

                doctena = await self._fetch_doctena_letter(client, keyword)
                mentions.extend(doctena)
                await asyncio.sleep(THROTTLE)

        logger.info("belgium_hcp_collected", count=len(mentions))
        return mentions

    async def _fetch_famhp_pharmacies(self, client: httpx.AsyncClient,
                                      keywords: List[str]) -> List[RawMention]:
        out: List[RawMention] = []
        try:
            resp = await client.get(FAMHP_PHARMACY_LIST)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            text_blob = soup.get_text(" ", strip=True).lower()
            kw_hits = [k for k in keywords if k.lower() in text_blob]
            if kw_hits:
                out.append(RawMention(
                    source_type="famhp_pharmacy_list",
                    source_url=FAMHP_PHARMACY_LIST,
                    country="BE",
                    language="en",
                    published_at=datetime.now(timezone.utc),
                    raw_text=(
                        "FAMHP/AFMPS public pharmacy register lists the licensed "
                        f"Belgian community pharmacies. Keywords matched: "
                        f"{', '.join(kw_hits)}. Use this register as the "
                        "canonical pharmacy universe for BE."
                    ),
                    query_used=kw_hits[0],
                    metadata={"register": "FAMHP public pharmacy list",
                              "match_kw": kw_hits},
                ))
        except Exception as exc:
            logger.warning("famhp_pharmacy_failed", error=str(exc))
        return out

    async def _fetch_inami(self, client: httpx.AsyncClient,
                           keyword: str) -> List[RawMention]:
        """INAMI/RIZIV NIHII lookup via the public silverpages app.

        silverpages is an ASP.NET + HTMX SPA that renders results client-side,
        so we drive Chromium via Playwright. Returns real records with
        Nom + N°INAMI + Profession + Qualification + Adresse de travail.

        Playwright is launched per-call here for simplicity; if traffic
        ever justifies it, hoist the browser into a module-level singleton
        kept alive across calls.
        """
        # Lazy import — keeps the module loadable on hosts without playwright.
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("inami_playwright_missing",
                           hint="pip install playwright && playwright install chromium")
            return []

        out: List[RawMention] = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                ctx = await browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    locale="fr-BE",
                )
                page = await ctx.new_page()
                try:
                    await page.goto(f"{INAMI_BASE}/Home",
                                    wait_until="domcontentloaded", timeout=15000)
                    try:
                        await page.click('#CookieButton', timeout=2500)
                    except Exception:
                        pass
                    await page.fill('#Form_Name', keyword)
                    await page.click('#LaunchSearch')
                    try:
                        await page.wait_for_selector(
                            '.card', state="attached", timeout=12000,
                        )
                    except Exception:
                        return []
                    # silverpages renders one .card per HCP result
                    cards = await page.eval_on_selector_all(
                        ".card",
                        "els => els.slice(0,10).map(e => "
                        "(e.innerText||'').replace(/\\s+/g,' ').trim())",
                    )
                finally:
                    await browser.close()

            for card_text in cards:
                if not card_text or len(card_text) < 30:
                    continue
                # Pull out NIHII pattern (123456-78) — quick sanity check
                import re as _re
                m = _re.search(r"N°INAMI\s+(\d{6}-\d{2})", card_text)
                nihii = m.group(1) if m else None
                if not nihii:
                    continue
                out.append(RawMention(
                    source_type="inami_riziv",
                    source_url=f"{INAMI_LOOKUP}?Form_Name={keyword}",
                    country="BE",
                    language="fr",
                    published_at=datetime.now(timezone.utc),
                    raw_text=card_text[:1500],
                    query_used=keyword,
                    metadata={
                        "register": "INAMI/RIZIV silverpages",
                        "nihii": nihii,
                    },
                ))
        except Exception as exc:
            logger.warning("inami_fetch_failed", kw=keyword, error=str(exc))
        return out

    async def _fetch_doctena_letter(self, client: httpx.AsyncClient,
                                    keyword: str) -> List[RawMention]:
        """Doctena BE indexes HCPs alphabetically; we hit the letter page
        matching the keyword and filter."""
        kw = keyword.strip().lower()
        if not kw or not kw[0].isalpha():
            return []
        letter = kw[0]
        out: List[RawMention] = []
        try:
            resp = await client.get(DOCTENA_DIRECTORY.format(letter=letter))
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            for card in soup.select("a.directory-item, li.directory-entry, article")[:30]:
                text = card.get_text(" ", strip=True)
                if not text or kw not in text.lower():
                    continue
                href = card.get("href", "")
                if href and not href.startswith("http"):
                    href = "https://www.doctena.be" + href
                out.append(RawMention(
                    source_type="doctena_be",
                    source_url=href or DOCTENA_DIRECTORY.format(letter=letter),
                    country="BE",
                    language="fr",
                    published_at=datetime.now(timezone.utc),
                    raw_text=text[:600],
                    query_used=keyword,
                    metadata={"register": "Doctena BE directory (opt-in)"},
                ))
                if len(out) >= 10:
                    break
        except Exception as exc:
            logger.warning("doctena_fetch_failed", kw=keyword, error=str(exc))
        return out