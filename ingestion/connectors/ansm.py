"""ANSM connector — France medicine shortages / availability.

ANSM (Agence nationale de sécurité du médicament et des produits de santé) is the
French medicines authority. Its "disponibilités des produits de santé" page is the
official list of medicines in / at risk of shortage — the highest-signal source for
the pharmacist `availability` topic in the FR-speaking market. It's the France
counterpart to the Belgian FAGG/AFMPS shortage feed in `belgium_health_data.py`.

How the source actually works (verified against the live site):
  • https://ansm.sante.fr/disponibilites-des-produits-de-sante/medicaments
    server-renders the COMPLETE current availability list as a single HTML
    `<table>` (~270 rows). There is no pagination and no JSON/REST export.
  • The page's `?search_api_fulltext=` box is **client-side only** — the server
    ignores it and always returns the full list. So we fetch the whole table ONCE,
    cache it for the run, and filter by drug / molecule name in Python.

Each row carries: status (Rupture de stock / Tension d'approvisionnement / Remise à
disposition / Arrêt de commercialisation), last-update date, the specialty name with
its active substance(s) in trailing `[...]`, expected resupply date, and the medical
domain. We match a brand by its trade name OR (better) its INN, because the list is
substance-led — that's why the batch passes ANSM the molecule for medicines.

Resilient: any non-200, network error, or selector miss degrades to an empty list
rather than raising — the live search treats `[]` as "no matches".
"""
import re
import unicodedata
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

ANSM_URL = "https://ansm.sante.fr/disponibilites-des-produits-de-sante/medicaments"
HEADERS = {
    "User-Agent": (
        "PharmaWatch/1.0 (+https://pharmawatch.eu/bot; "
        "contact=dpo@pharmawatch.eu; FR pharma intelligence)"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}


def _norm(s: str) -> str:
    """Accent- and case-insensitive key for matching ('paracétamol' → 'paracetamol')."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(c) != "Mn"
    ).lower()


def _parse_date(text: str) -> Optional[datetime]:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", text or "")
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d, tzinfo=timezone.utc)
    except ValueError:
        return None


class ANSMConnector(BaseConnector):
    source_type = "ansm_shortage"

    def __init__(self):
        # Cache the full list for the lifetime of the connector instance so a
        # batch over thousands of brands fetches the page once, not once per brand.
        self._records: Optional[List[dict]] = None

    def is_available(self) -> bool:
        return True  # public surface, no key

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

        records = await self._get_records()
        if not records:
            return []

        norm_kws = [_norm(k) for k in keywords if _norm(k)]
        if not norm_kws:
            return []

        out: List[RawMention] = []
        seen_ids: set = set()
        for rec in records:
            hay = rec["_norm"]
            if not any(kw in hay for kw in norm_kws):
                continue
            rid = rec.get("id") or rec["product"]
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            substances = ", ".join(rec["substances"]) if rec["substances"] else ""
            body = f"{rec['status']} — {rec['product']}"
            if rec["medical_domain"]:
                body += f" · {rec['medical_domain']}"
            if rec["resupply"]:
                body += f" · remise à disposition prévue {rec['resupply']}"
            out.append(RawMention(
                source_type=self.source_type,
                source_url=rec.get("detail_url") or ANSM_URL,
                country="FR",
                language="fr",
                published_at=rec.get("updated_dt") or datetime.now(timezone.utc),
                raw_text=body[:1500],
                query_used=keywords[0] if keywords else "",
                metadata={
                    "register": "ANSM",
                    "signal": "shortage",
                    "status": rec["status"],
                    "substances": rec["substances"],
                    "medical_domain": rec["medical_domain"],
                },
            ))
            if len(out) >= 10:
                break

        logger.info("ansm_collected", count=len(out), keywords=keywords[:3])
        return out

    async def _get_records(self) -> List[dict]:
        if self._records is not None:
            return self._records
        self._records = []
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=30.0,
                                         follow_redirects=True) as client:
                resp = await client.get(ANSM_URL)
            if resp.status_code != 200:
                logger.warning("ansm_fetch_failed", status=resp.status_code)
                return self._records
            self._records = self._parse(resp.text)
            logger.info("ansm_list_loaded", rows=len(self._records))
        except Exception as exc:  # noqa: BLE001
            logger.warning("ansm_fetch_error", error=str(exc))
        return self._records

    @staticmethod
    def _parse(html: str) -> List[dict]:
        soup = BeautifulSoup(html, "html.parser")
        out: List[dict] = []
        for tr in soup.select("table tbody tr"):
            tds = tr.find_all(["td", "th"])
            if len(tds) < 5:
                continue
            spec = tds[2].get_text(" ", strip=True)
            m = re.search(r"\[(.*?)\]\s*$", spec)
            substances = (
                [s.strip() for s in re.split(r",|;", m.group(1)) if s.strip()]
                if m else []
            )
            status = tds[0].get_text(" ", strip=True)
            updated = tds[1].get_text(" ", strip=True)
            domain = tds[4].get_text(" ", strip=True)
            href = tr.get("data-href")
            rec = {
                "id": tr.get("data-id"),
                "status": status,
                "updated": updated,
                "updated_dt": _parse_date(updated),
                "product": spec,
                "substances": substances,
                "resupply": tds[3].get_text(" ", strip=True) or None,
                "medical_domain": domain,
                "detail_url": ("https://ansm.sante.fr" + href) if href else None,
            }
            rec["_norm"] = _norm(spec + " " + " ".join(substances))
            out.append(rec)
        return out