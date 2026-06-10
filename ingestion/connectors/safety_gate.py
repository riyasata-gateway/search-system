"""EU Safety Gate (RAPEX) connector — cosmetic / personal-care safety alerts.

Safety Gate is the EU rapid-alert system for dangerous non-food products. It
covers cosmetics and personal-care items (and toys, electricals, …) but, by
design, NOT medicines or medical devices — so it's the right recall/safety
channel for the dermocosmetic / parapharmacy slice of the OTC category.

Source: the OpenDataSoft public mirror of RAPEX (`healthref-europe-rapex-en`),
which is refreshed daily and exposes a keyless REST API with server-side
filtering by `product_category` (= "Cosmetics") — far more usable than the
official EC search API (POST-only, anonymous search disabled). We pull the
Cosmetics alerts once, cache them for the run, and match each tracked brand
against the alert's `product_brand` / `product_name`.

Resilient: any error degrades to an empty list rather than raising.
"""
import re
import unicodedata
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

ODS_BASE = (
    "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
    "healthref-europe-rapex-en/records"
)
_SELECT = (
    "alert_number,alert_date,alert_level,product_brand,product_name,"
    "product_category,alert_description,risk_legal_provision,alert_country,"
    "alert_other_countries,rapex_url"
)
# Pull the FULL cosmetics-alert set (the loop stops when rows run out). The old
# 2000 "newest" cap reached back only to ~2025 and silently MISSED matches for
# tracked brands whose alerts are older (e.g. Vichy 2022, most Nivea/Garnier) —
# producing a false "0 matches". RAPEX cosmetics total ~5.4k; ODS offset cap is
# 10000, so this fetches everything in one paginated pass.
_MAX_RECORDS = 10000
_PAGE = 100


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s or "")
                if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# Generic words that appear as standalone brand "names" in our catalogue but
# collide with unrelated cosmetic product descriptions in RAPEX.
_GENERIC = {"life", "magic", "crystal", "energy", "life energy", "pure", "natural",
            "beauty", "care", "active", "bio", "med", "plus", "gold"}


class SafetyGateConnector(BaseConnector):
    source_type = "safety_gate"

    def __init__(self):
        self._alerts: Optional[List[dict]] = None

    def is_available(self) -> bool:
        return True  # keyless public API

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        alerts = await self._get_alerts()
        if not alerts:
            return []

        # Match on the brand trade name. An exact match against the alert's brand
        # field is trusted at any length; looser token-containment (brand or
        # product name) is only allowed for names of length >= 4 to avoid spurious
        # substring hits. Generic dictionary words are excluded outright — they
        # collide with unrelated product names (e.g. "LIFE", "MAGIC").
        norm_kws = [k for k in (_norm(x) for x in keywords) if k and k not in _GENERIC]
        if not norm_kws:
            return []

        out: List[RawMention] = []
        seen: set = set()
        for a in alerts:
            brand_n = a["_brand_norm"]
            name_n = a["_name_norm"]
            matched = any(
                kw == brand_n
                or (len(kw) >= 4 and (f" {kw} " in f" {brand_n} " or f" {kw} " in f" {name_n} "))
                for kw in norm_kws
            )
            if not matched:
                continue
            num = a.get("alert_number") or a.get("rapex_url")
            if num in seen:
                continue
            seen.add(num)
            body = (
                f"Safety Gate alert ({a.get('alert_level') or 'risk'}): "
                f"{a.get('product_brand') or ''} {a.get('product_name') or ''}".strip()
            )
            if a.get("alert_description"):
                body += f" — {a['alert_description']}"
            out.append(RawMention(
                source_type=self.source_type,
                source_url=a.get("rapex_url") or "https://ec.europa.eu/safety-gate-alerts/",
                country=_country_code(a.get("alert_country")),
                language="en",
                published_at=_parse_date(a.get("alert_date")),
                raw_text=body[:1500],
                query_used=keywords[0] if keywords else "",
                metadata={
                    "register": "EU Safety Gate (RAPEX)",
                    "signal": "recall",
                    "alert_level": a.get("alert_level"),
                    "category": a.get("product_category"),
                    "alert_number": a.get("alert_number"),
                    "alert_country": a.get("alert_country"),
                    "other_countries": a.get("alert_other_countries"),
                },
            ))
            if len(out) >= 60:   # per-brand cap (was 10 — a brand can have many alerts)
                break

        logger.info("safety_gate_collected", count=len(out), keywords=keywords[:3])
        return out

    async def _get_alerts(self) -> List[dict]:
        if self._alerts is not None:
            return self._alerts
        self._alerts = []
        try:
            async with httpx.AsyncClient(timeout=30.0,
                                         headers={"User-Agent": "PharmaWatch/1.0"}) as client:
                offset = 0
                while offset < _MAX_RECORDS:
                    params = {
                        "where": 'product_category="Cosmetics"',
                        "order_by": "alert_date desc",
                        "limit": _PAGE,
                        "offset": offset,
                        "select": _SELECT,
                    }
                    r = await client.get(ODS_BASE, params=params)
                    if r.status_code != 200:
                        logger.warning("safety_gate_fetch_failed", status=r.status_code, offset=offset)
                        break
                    rows = r.json().get("results") or []
                    if not rows:
                        break
                    for a in rows:
                        a["_brand_norm"] = _norm(a.get("product_brand") or "")
                        a["_name_norm"] = _norm(a.get("product_name") or "")
                    self._alerts.extend(rows)
                    offset += _PAGE
            logger.info("safety_gate_loaded", alerts=len(self._alerts))
        except Exception as exc:  # noqa: BLE001
            logger.warning("safety_gate_fetch_error", error=str(exc))
        return self._alerts


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


_COUNTRY = {
    "Belgium": "BE", "France": "FR", "Netherlands": "NL", "Germany": "DE",
}


def _country_code(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return _COUNTRY.get(name.strip(), None)
