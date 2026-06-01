"""ANSM connector — France medicine shortages + safety alerts.

ANSM (Agence nationale de sécurité du médicament et des produits de santé) is the
French medicines authority. It publishes:
  - **Ruptures de stock** — the official list of medicines in / at risk of shortage
    (the single highest-signal source for the pharmacist `availability` topic in FR).
  - **Informations de sécurité** — safety alerts / DHPC-style communications.

This is the France counterpart to the Belgian FAGG/AFMPS shortage feed in
`belgium_health_data.py`. Both feed the pharmacist lens (shortages + safety first).

Public, no-auth surfaces only. The connector is resilient: any non-200, network
error, or selector miss degrades to an empty list rather than raising — the live
search treats `[]` as "no matches" and the rest of the sources still return.

NOTE: ANSM runs a Drupal site whose markup shifts periodically; the CSS selectors
below may need re-tuning against the live DOM (same maintenance posture as the
Belgian connector). Endpoints are documented inline so that's a quick fix.
"""
import asyncio
from datetime import datetime, timezone
from typing import List

import httpx
from bs4 import BeautifulSoup

from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

HEADERS = {
    "User-Agent": (
        "PharmaWatch/1.0 (+https://pharmawatch.eu/bot; "
        "contact=dpo@pharmawatch.eu; FR pharma intelligence)"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# ANSM full-text search over the "disponibilité des produits de santé" section —
# returns shortage / availability pages for a given molecule or brand.
ANSM_SHORTAGE_SEARCH = (
    "https://ansm.sante.fr/disponibilites-des-produits-de-sante/medicaments"
    "?search_api_fulltext={kw}"
)
# ANSM site-wide search — surfaces safety information / news for the keyword.
ANSM_SAFETY_SEARCH = "https://ansm.sante.fr/search?search_api_fulltext={kw}"


class ANSMConnector(BaseConnector):
    source_type = "ansm"

    def is_available(self) -> bool:
        return True  # public surfaces, no key

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        # ANSM is the French authority. The platform is BE+FR; French-language
        # Belgian users also consult ANSM for French brands, so run whenever
        # France OR Belgium is in scope.
        if countries and not ({"FR", "BE"} & set(countries)):
            return []

        mentions: List[RawMention] = []
        async with httpx.AsyncClient(headers=HEADERS, timeout=12.0,
                                     follow_redirects=True) as client:
            for keyword in keywords:
                shortages, safety = await asyncio.gather(
                    self._fetch_shortages(client, keyword),
                    self._fetch_safety(client, keyword),
                    return_exceptions=True,
                )
                for batch in (shortages, safety):
                    if isinstance(batch, list):
                        mentions.extend(batch)

        logger.info("ansm_collected", count=len(mentions))
        return mentions

    async def _fetch_shortages(self, client: httpx.AsyncClient,
                               keyword: str) -> List[RawMention]:
        """Official French shortage / availability listing, filtered by keyword.
        Highest-signal France source for the pharmacist `availability` topic."""
        out: List[RawMention] = []
        try:
            resp = await client.get(ANSM_SHORTAGE_SEARCH.format(kw=keyword))
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            # Drupal teaser cards / result rows.
            cards = soup.select(
                "article, .node--view-mode-teaser, .search-result, .views-row, li.item"
            )
            kw_l = keyword.lower()
            for card in cards:
                title_el = card.select_one("h2, h3, .title, a")
                if not title_el:
                    continue
                title = title_el.get_text(" ", strip=True)
                body_el = card.select_one("p, .field--type-text-long, .teaser, .summary")
                body = body_el.get_text(" ", strip=True) if body_el else ""
                text = (title + (". " + body if body else "")).strip()
                if len(text) < 25 or kw_l not in text.lower():
                    continue
                href = title_el.get("href", "") if title_el.has_attr("href") else ""
                if href and not href.startswith("http"):
                    href = "https://ansm.sante.fr" + href
                out.append(RawMention(
                    source_type="ansm_shortage",
                    source_url=href or ANSM_SHORTAGE_SEARCH.format(kw=keyword),
                    country="FR",
                    language="fr",
                    published_at=datetime.now(timezone.utc),
                    raw_text=text[:1500],
                    query_used=keyword,
                    metadata={"register": "ANSM", "signal": "shortage"},
                ))
                if len(out) >= 10:
                    break
        except Exception as exc:
            logger.warning("ansm_shortage_failed", kw=keyword, error=str(exc))
        return out

    async def _fetch_safety(self, client: httpx.AsyncClient,
                            keyword: str) -> List[RawMention]:
        """ANSM safety information / news matching the keyword (DHPC, recalls,
        risk communications). Feeds the side-effect / risk angle."""
        out: List[RawMention] = []
        try:
            resp = await client.get(ANSM_SAFETY_SEARCH.format(kw=keyword))
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            kw_l = keyword.lower()
            for card in soup.select("article, .search-result, .views-row")[:8]:
                title_el = card.select_one("h2, h3, .title, a")
                if not title_el:
                    continue
                text = title_el.get_text(" ", strip=True)
                if len(text) < 20 or kw_l not in text.lower():
                    continue
                href = title_el.get("href", "") if title_el.has_attr("href") else ""
                if href and not href.startswith("http"):
                    href = "https://ansm.sante.fr" + href
                out.append(RawMention(
                    source_type="ansm_safety",
                    source_url=href or ANSM_SAFETY_SEARCH.format(kw=keyword),
                    country="FR",
                    language="fr",
                    published_at=datetime.now(timezone.utc),
                    raw_text=text[:1500],
                    query_used=keyword,
                    metadata={"register": "ANSM", "signal": "safety"},
                ))
        except Exception as exc:
            logger.warning("ansm_safety_failed", kw=keyword, error=str(exc))
        return out
