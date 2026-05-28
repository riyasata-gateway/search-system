"""openFDA connector — drug labels + adverse-event reports (FAERS surfacing).

Free, key-optional. Closes the "pharmacovigilance public databases" gap by
giving us a direct line to FAERS (adverse events) and the SPL drug-label
corpus. Each query hits two endpoints in parallel:

  /drug/label.json   — structured product label content
  /drug/event.json   — FAERS adverse-event reports

Both are dollar-zero. With an FDA_API_KEY env var, rate limits go from 240/min
to 120,000/day per key — we don't require one to start.
"""
import asyncio
from datetime import datetime, timezone
from typing import List

import httpx

from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

LABEL_API = "https://api.fda.gov/drug/label.json"
EVENT_API = "https://api.fda.gov/drug/event.json"
_HEADERS = {"User-Agent": "PharmaWatch/1.0"}


def _parse_fda_date(raw: str):
    """openFDA dates come as YYYYMMDD."""
    if not raw or len(raw) < 8:
        return None
    try:
        return datetime.strptime(raw[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class OpenFDAConnector(BaseConnector):
    source_type = "openfda"

    async def _fetch_labels(self, client: httpx.AsyncClient, keyword: str) -> List[RawMention]:
        out: List[RawMention] = []
        try:
            resp = await client.get(
                LABEL_API,
                params={
                    "search": f'openfda.brand_name:"{keyword}" OR openfda.generic_name:"{keyword}"',
                    "limit": 5,
                },
            )
            if resp.status_code != 200:
                return []
            for entry in resp.json().get("results", []):
                ofda = entry.get("openfda", {}) or {}
                brand = (ofda.get("brand_name") or [""])[0]
                generic = (ofda.get("generic_name") or [""])[0]
                indications = " ".join(entry.get("indications_and_usage", []) or [])
                warnings = " ".join(entry.get("warnings", []) or [])
                title = brand or generic or "FDA drug label"
                body_chunks = []
                if indications:
                    body_chunks.append(f"Indications: {indications[:400]}")
                if warnings:
                    body_chunks.append(f"Warnings: {warnings[:300]}")
                text = f"{title}. " + " ".join(body_chunks)
                text = text.strip().rstrip(".")
                if len(text) < 40:
                    continue
                set_id = entry.get("set_id")
                url = f"https://labels.fda.gov/?setid={set_id}" if set_id else "https://open.fda.gov/apis/drug/label/"
                published_at = _parse_fda_date(entry.get("effective_time", ""))
                out.append(
                    RawMention(
                        source_type=self.source_type,
                        source_url=url,
                        country=None,
                        language="en",
                        published_at=published_at,
                        raw_text=text[:1200],
                        query_used=keyword,
                        engagement_count=None,
                        metadata={
                            "subtype": "label",
                            "brand_name": brand,
                            "generic_name": generic,
                        },
                    )
                )
        except Exception as exc:
            logger.warning("openfda_label_failed", keyword=keyword, error=str(exc))
        return out

    async def _fetch_events(self, client: httpx.AsyncClient, keyword: str) -> List[RawMention]:
        out: List[RawMention] = []
        try:
            resp = await client.get(
                EVENT_API,
                params={
                    "search": (
                        f'patient.drug.openfda.brand_name:"{keyword}" '
                        f'OR patient.drug.openfda.generic_name:"{keyword}"'
                    ),
                    "limit": 5,
                },
            )
            if resp.status_code != 200:
                return []
            for entry in resp.json().get("results", []):
                reactions = entry.get("patient", {}).get("reaction", []) or []
                reaction_terms = [r.get("reactionmeddrapt", "") for r in reactions if r.get("reactionmeddrapt")]
                if not reaction_terms:
                    continue
                serious = entry.get("serious", "0") == "1"
                report_date = _parse_fda_date(entry.get("receivedate", ""))
                report_id = entry.get("safetyreportid", "")
                drugs = entry.get("patient", {}).get("drug", []) or []
                drug_names = [
                    (d.get("openfda", {}).get("brand_name") or [None])[0] for d in drugs
                ]
                drug_names = [n for n in drug_names if n]
                primary_drug = drug_names[0] if drug_names else keyword
                text = (
                    f"FAERS report ({report_id}) — drug: {primary_drug}; "
                    f"reactions: {', '.join(reaction_terms[:6])}"
                    + (" — flagged serious." if serious else ".")
                )
                if len(text) < 30:
                    continue
                out.append(
                    RawMention(
                        source_type=self.source_type,
                        source_url=f"https://api.fda.gov/drug/event.json?search=safetyreportid:{report_id}",
                        country=None,
                        language="en",
                        published_at=report_date,
                        raw_text=text[:1200],
                        query_used=keyword,
                        engagement_count=None,
                        metadata={
                            "subtype": "adverse_event",
                            "serious": serious,
                            "report_id": report_id,
                            "reactions": reaction_terms[:10],
                        },
                    )
                )
        except Exception as exc:
            logger.warning("openfda_event_failed", keyword=keyword, error=str(exc))
        return out

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        mentions: List[RawMention] = []
        async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS) as client:
            for keyword in keywords:
                labels, events = await asyncio.gather(
                    self._fetch_labels(client, keyword),
                    self._fetch_events(client, keyword),
                    return_exceptions=True,
                )
                if isinstance(labels, list):
                    mentions.extend(labels)
                if isinstance(events, list):
                    mentions.extend(events)

        logger.info("openfda_collected", count=len(mentions))
        return mentions
