"""ClinicalTrials.gov connector — clinical signal grounding.

Free public REST API v2 (api.clinicaltrials.gov). Returns trial protocol
metadata: phase, status, sponsor, conditions, interventions. Designed as a
trusted authoritative source for AI grounding and lab-side competitive intel.
"""
from datetime import datetime, timezone
from typing import List

import httpx

from core.logging import get_logger
from ingestion.connectors.base import BaseConnector, RawMention

logger = get_logger(__name__)

CT_API = "https://clinicaltrials.gov/api/v2/studies"
_HEADERS = {"User-Agent": "PharmaWatch/1.0", "Accept": "application/json"}
# Safety cap on the paginated fetch (runaway guard for a pathological broad
# term), NOT an arbitrary content limit — molecules rarely exceed this.
_MAX_STUDIES_PER_KW = 300


class ClinicalTrialsConnector(BaseConnector):
    source_type = "clinical_trials"

    async def collect(
        self,
        keywords: List[str],
        countries: List[str],
        languages: List[str],
    ) -> List[RawMention]:
        mentions: List[RawMention] = []
        seen_ids: set = set()

        async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS) as client:
            for keyword in keywords:
                try:
                    # Fetch ALL trials for the molecule (was capped at 8) by following
                    # the API's nextPageToken; a generous safety cap guards against a
                    # pathological broad term, it is not an arbitrary content limit.
                    studies, token = [], None
                    while len(studies) < _MAX_STUDIES_PER_KW:
                        params = {"query.term": keyword, "pageSize": 100,
                                  "format": "json", "sort": "LastUpdatePostDate:desc"}
                        if token:
                            params["pageToken"] = token
                        resp = await client.get(CT_API, params=params)
                        if resp.status_code != 200:
                            break
                        data = resp.json()
                        studies.extend(data.get("studies", []) or [])
                        token = data.get("nextPageToken")
                        if not token:
                            break
                    if not studies:
                        continue
                except Exception as exc:
                    logger.warning("clinical_trials_failed", keyword=keyword, error=str(exc))
                    continue

                for study in studies:
                    proto = study.get("protocolSection", {}) or {}
                    ident = proto.get("identificationModule", {}) or {}
                    status = proto.get("statusModule", {}) or {}
                    design = proto.get("designModule", {}) or {}
                    sponsor = proto.get("sponsorCollaboratorsModule", {}) or {}
                    conditions_mod = proto.get("conditionsModule", {}) or {}

                    nct_id = ident.get("nctId")
                    if not nct_id or nct_id in seen_ids:
                        continue
                    seen_ids.add(nct_id)

                    brief_title = (ident.get("briefTitle") or "").strip()
                    if not brief_title:
                        continue
                    phase = ", ".join(design.get("phases", []) or []) or "N/A"
                    study_type = design.get("studyType", "")  # INTERVENTIONAL / OBSERVATIONAL
                    overall_status = status.get("overallStatus", "")
                    lead_sponsor = (sponsor.get("leadSponsor", {}) or {}).get("name", "")
                    conditions = ", ".join(conditions_mod.get("conditions", []) or [])

                    parts = [brief_title]
                    if phase != "N/A":
                        parts.append(f"Phase: {phase}")
                    if overall_status:
                        parts.append(f"Status: {overall_status}")
                    if lead_sponsor:
                        parts.append(f"Sponsor: {lead_sponsor}")
                    if conditions:
                        parts.append(f"Conditions: {conditions}")
                    text = ". ".join(parts).strip().rstrip(".")
                    if len(text) < 30:
                        continue

                    last_update = status.get("lastUpdatePostDateStruct", {}).get("date")
                    published_at = None
                    if last_update:
                        try:
                            published_at = datetime.strptime(last_update, "%Y-%m-%d").replace(
                                tzinfo=timezone.utc
                            )
                        except ValueError:
                            pass

                    mentions.append(
                        RawMention(
                            source_type=self.source_type,
                            source_url=f"https://clinicaltrials.gov/study/{nct_id}",
                            country=None,
                            language="en",
                            published_at=published_at,
                            raw_text=text[:1200],
                            query_used=keyword,
                            engagement_count=None,
                            metadata={
                                "nct_id": nct_id,
                                "phase": phase,
                                "study_type": study_type,
                                "status": overall_status,
                                "sponsor": lead_sponsor,
                            },
                        )
                    )

        logger.info("clinical_trials_collected", count=len(mentions))
        return mentions
