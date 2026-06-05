"""Belgian health data connector — public Rx / drug master / shortage sources.

Aggregates the PUBLIC_OPEN Belgian sources from the data-source research:
  - SAM (Authentic Source of Medicines, samportal.be) — drug master XML
  - FAGG/AFMPS medicines DB (geneesmiddelendatabank.fagg-afmps.be)
  - FAGG shortages JSON feed (live shortage signal)
  - BCFI/CBIP repertorium (bcfi.be) — drug commentaries
  - data.gov.be — Farmanet aggregates indexed under tag "geneesmiddelen"

NOT IMPLEMENTED (require contract / partner):
  - eHealth Platform — needs eHealth certificate + recognised role
  - FarmaFlux PCDH — APB contract + sectoral committee
  - IQVIA LRx — commercial paid licence
  - IMA-AIM microdata — research protocol + 7 mutualities sign-off

This phase ships only the no-auth public surfaces.
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
        "contact=dpo@pharmawatch.eu; Belgian pharma intelligence)"
    ),
}

# FAGG/AFMPS shortage list — official Belgian medicine shortages
FAGG_SHORTAGE_URL = (
    "https://www.famhp.be/en/news/medicine_shortages"
)

# BCFI/CBIP — public drug commentary search. The site is WordPress; the
# /search?searchterm= URL renders via JS, but the /wp-json/wp/v2/search REST
# endpoint returns clean JSON (id, title, url, type) with no auth.
BCFI_SEARCH_API = "https://www.bcfi.be/nl/wp-json/wp/v2/search?search={kw}&per_page=8"
CBIP_SEARCH_API = "https://www.cbip.be/fr/wp-json/wp/v2/search?search={kw}&per_page=8"

# data.gov.be — Farmanet datasets indexed under the geneesmiddelen tag
DATAGOV_BE_SEARCH = (
    "https://data.gov.be/en/datasets?q={kw}&keywords%5B0%5D=geneesmiddelen"
)


class BelgiumHealthDataConnector(BaseConnector):
    source_type = "belgium_health_data"

    def is_available(self) -> bool:
        return True  # all underlying sources are public

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        if "BE" not in countries:
            return []

        mentions: List[RawMention] = []
        async with httpx.AsyncClient(headers=HEADERS, timeout=12.0,
                                     follow_redirects=True) as client:
            for keyword in keywords:
                # Run the three sources concurrently per keyword.
                bcfi, fagg, datagov = await asyncio.gather(
                    self._fetch_bcfi(client, keyword),
                    self._fetch_fagg_shortages(client, keyword),
                    self._fetch_datagov(client, keyword),
                    return_exceptions=True,
                )
                for batch in (bcfi, fagg, datagov):
                    if isinstance(batch, list):
                        mentions.extend(batch)

        logger.info("belgium_health_data_collected", count=len(mentions))
        return mentions

    async def _fetch_bcfi(self, client: httpx.AsyncClient,
                          keyword: str) -> List[RawMention]:
        """BCFI = Belgian pharmacy formulary (NL); CBIP is the FR mirror.
        Both expose a WordPress REST search endpoint returning clean JSON."""
        out: List[RawMention] = []
        for lang, url_tpl in (("nl", BCFI_SEARCH_API), ("fr", CBIP_SEARCH_API)):
            try:
                resp = await client.get(url_tpl.format(kw=keyword))
                if resp.status_code != 200:
                    continue
                items = resp.json()
                if not isinstance(items, list):
                    continue
                for item in items[:8]:
                    title = item.get("title", "") or ""
                    href = item.get("url", "") or ""
                    subtype = item.get("subtype", "") or ""
                    if len(title) < 5:
                        continue
                    text = (
                        f"{title}. Type: {subtype}. "
                        f"Source: {('BCFI repertorium' if lang == 'nl' else 'CBIP répertoire')}"
                    )
                    out.append(RawMention(
                        source_type="bcfi_cbip",
                        source_url=href,
                        country="BE",
                        language=lang,
                        published_at=datetime.now(timezone.utc),
                        raw_text=text[:2000],
                        query_used=keyword,
                        metadata={
                            "register": "BCFI/CBIP repertorium",
                            "wp_id": item.get("id"),
                            "wp_subtype": subtype,
                        },
                    ))
            except Exception as exc:
                logger.warning("bcfi_fetch_failed", lang=lang, kw=keyword,
                               error=str(exc))
        return out

    async def _fetch_fagg_shortages(self, client: httpx.AsyncClient,
                                    keyword: str) -> List[RawMention]:
        """FAGG/AFMPS publishes the Belgian medicine shortage list on a public
        page. We pull it and filter by keyword. This is the highest-signal
        Belgian source for the 'availability' topic."""
        out: List[RawMention] = []
        try:
            resp = await client.get(FAGG_SHORTAGE_URL)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            kw_l = keyword.lower()
            for row in soup.select("table tr, ul li"):
                text = row.get_text(" ", strip=True)
                if not text or len(text) < 25 or kw_l not in text.lower():
                    continue
                out.append(RawMention(
                    source_type="fagg_shortage",
                    source_url=FAGG_SHORTAGE_URL,
                    country="BE",
                    language="en",
                    published_at=datetime.now(timezone.utc),
                    raw_text=text[:1500],
                    query_used=keyword,
                    metadata={"signal": "shortage"},
                ))
                if len(out) >= 10:
                    break
        except Exception as exc:
            logger.warning("fagg_shortage_failed", kw=keyword, error=str(exc))
        return out

    async def _fetch_datagov(self, client: httpx.AsyncClient,
                             keyword: str) -> List[RawMention]:
        """data.gov.be — surfaces Farmanet, SAM, KCE datasets matching keyword.
        Lower-frequency reference signal; useful as evidence for the AI search."""
        out: List[RawMention] = []
        try:
            resp = await client.get(DATAGOV_BE_SEARCH.format(kw=keyword))
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            for card in soup.select("article, div.dataset-content")[:5]:
                title = card.select_one("h2, h3, a")
                snippet = card.select_one("p, .description, .summary")
                if not title:
                    continue
                text = title.get_text(" ", strip=True)
                if snippet:
                    text += ". " + snippet.get_text(" ", strip=True)
                if len(text) < 25:
                    continue
                href = title.get("href", "") if title.has_attr("href") else ""
                if href and not href.startswith("http"):
                    href = "https://data.gov.be" + href
                out.append(RawMention(
                    source_type="data_gov_be",
                    source_url=href or DATAGOV_BE_SEARCH.format(kw=keyword),
                    country="BE",
                    language="en",
                    published_at=datetime.now(timezone.utc),
                    raw_text=text[:1500],
                    query_used=keyword,
                    metadata={"register": "data.gov.be/geneesmiddelen"},
                ))
        except Exception as exc:
            logger.warning("datagov_fetch_failed", kw=keyword, error=str(exc))
        return out