"""BCFI / CBIP connector — authoritative Belgian clinical commentary.

BCFI/CBIP (Belgian Centre for Pharmacotherapeutic Information) is the national
prescribing-guidance authority. Its structured Repertorium (interaction tables,
monographs) is a JS-embedded app with no public API, BUT its *Folia* clinical
commentary IS queryable via the WordPress REST API — and that's where the
actionable Belgian signal lives: interaction warnings, special-population
(older-patient / pregnancy) guidance, safety notes and de-prescribing advice per
substance.

We query Folia by the brand's active substance (FR + NL) and return each clinical
note as a `bcfi` mention. Substance-keyed, so caller passes the INN, not the brand.
"""
from datetime import datetime, timezone
from typing import List

import httpx

from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

_SEARCH = "https://www.bcfi.be/{lang}/wp-json/wp/v2/search"
_HEADERS = {"User-Agent": "PharmaWatch/1.0 (EU pharma research; +https://pharmawatch.eu/bot)"}
_MAX_PER_KW = 50   # was 8 — too few results per keyword (silent under-fetch)


class BCFIConnector(BaseConnector):
    source_type = "bcfi"

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        kws = [k for k in keywords if k and len(k) >= 3]
        if not kws:
            return []
        # Belgium is bilingual — query both FR and NL Folia.
        langs = [l for l in ("nl", "fr") if l in (languages or ["nl", "fr"])] or ["nl", "fr"]

        mentions: List[RawMention] = []
        seen: set = set()
        async with httpx.AsyncClient(headers=_HEADERS, timeout=15.0, follow_redirects=True) as client:
            for lang in langs:
                for kw in kws:
                    try:
                        r = await client.get(_SEARCH.format(lang=lang),
                                             params={"search": kw, "per_page": _MAX_PER_KW})
                        if r.status_code != 200:
                            continue
                        items = r.json()
                    except Exception as exc:
                        logger.warning("bcfi_search_failed", kw=kw, lang=lang, error=str(exc))
                        continue
                    for it in items:
                        url = it.get("url")
                        title = (it.get("title") or "").strip()
                        if not url or not title or url in seen:
                            continue
                        seen.add(url)
                        mentions.append(RawMention(
                            source_type=self.source_type,
                            source_url=url,
                            country="BE",
                            language=lang,
                            published_at=datetime.now(timezone.utc),
                            raw_text=f"BCFI/CBIP clinical note — {title}",
                            query_used=kw,
                            metadata={"substance": kw, "register": "BCFI Folia"},
                        ))
        logger.info("bcfi_collected", count=len(mentions))
        return mentions
