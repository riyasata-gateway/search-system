"""HCP Targeting — interface-ready stub.

The Phase 2 component "HCP Targeting by prescriber momentum" requires KOL
graph data we don't yet have (Doctolib, LinkedIn medical, Veeva CRM, or
de-identified prescription data). Rather than skip this slot, we ship a
clean, fully-typed interface plus a discoverable "no data" path so that:

  1. Frontend / orchestrator code can call this today and render a
     "HCP data not yet available — connect Veeva/Doctolib in Setup" card
     instead of hard-coding the absence elsewhere.
  2. When a real KOL data source is wired (`models.hcp.HCP` and an
     ingestion connector), this module replaces `_query_hcp_signals` with
     the real query — every caller keeps working unchanged.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from core.logging import get_logger
from intelligence.output_schema import MetricBundle, as_score
from models.brand import Brand

logger = get_logger(__name__)


class HCPDataStatus(str, enum.Enum):
    available = "available"
    not_connected = "not_connected"      # no HCP source wired
    insufficient = "insufficient"        # connected but too little data
    error = "error"


@dataclass
class HCPTarget:
    hcp_id: str
    name: str
    specialty: Optional[str]
    region: Optional[str]
    prescriber_momentum: float           # 0–100 SCORE
    reach_priority: str                  # "high" | "medium" | "low"
    rationale: str


@dataclass
class HCPTargetingResult:
    brand_id: int
    brand_name: str
    country: Optional[str]
    data_status: HCPDataStatus
    message: str
    targets: List[HCPTarget] = field(default_factory=list)
    next_step_for_admin: Optional[str] = None

    def to_bundle(self) -> MetricBundle:
        if self.data_status != HCPDataStatus.available or not self.targets:
            return MetricBundle(
                name="hcp_targeting",
                metrics=[as_score(0.0, f"HCP Targeting: {self.data_status.value}")],
                context={
                    "brand_id": self.brand_id,
                    "country": self.country,
                    "status": self.data_status.value,
                    "message": self.message,
                    "next_step_for_admin": self.next_step_for_admin,
                },
            )
        top = max(t.prescriber_momentum for t in self.targets)
        return MetricBundle(
            name="hcp_targeting",
            metrics=[as_score(top, f"Top HCP momentum", sample_size=len(self.targets))],
            context={
                "brand_id": self.brand_id,
                "country": self.country,
                "status": self.data_status.value,
                "targets": [
                    {
                        "hcp_id": t.hcp_id,
                        "name": t.name,
                        "specialty": t.specialty,
                        "region": t.region,
                        "prescriber_momentum": t.prescriber_momentum,
                        "reach_priority": t.reach_priority,
                        "rationale": t.rationale,
                    }
                    for t in self.targets
                ],
            },
        )


def _query_hcp_signals(
    db: Session,
    brand_id: int,
    country: Optional[str],
    limit: int,
) -> Optional[List[HCPTarget]]:
    """Replace this when the HCP data model lands.

    Today: returns None to signal that no HCP source is wired. The shape of
    the future implementation should be: query an HCP table joined with
    PrescriptionEvent (or analogous) — compute per-HCP momentum on Rx volume
    over time, rank by acceleration, attach specialty/region from the HCP
    record, and emit HCPTarget objects.
    """
    return None


def rank_hcps(
    db: Session,
    brand_id: int,
    country: Optional[str] = None,
    limit: int = 20,
) -> Optional[HCPTargetingResult]:
    brand = db.get(Brand, brand_id)
    if brand is None:
        return None

    targets = _query_hcp_signals(db, brand_id, country, limit)
    if targets is None:
        # No HCP data source connected yet.
        result = HCPTargetingResult(
            brand_id=brand_id,
            brand_name=brand.name,
            country=country,
            data_status=HCPDataStatus.not_connected,
            message=(
                "HCP targeting requires a connected KOL / prescriber data source. "
                "No source is wired in this environment."
            ),
            next_step_for_admin=(
                "Connect one of: Doctolib API, LinkedIn Medical insights, Veeva CRM, "
                "or de-identified Rx pattern feed. See Setup → Integrations."
            ),
        )
        logger.info("hcp_targeting_no_data", brand_id=brand_id, country=country)
        return result

    if not targets:
        return HCPTargetingResult(
            brand_id=brand_id,
            brand_name=brand.name,
            country=country,
            data_status=HCPDataStatus.insufficient,
            message="HCP data source is connected but no targets met momentum threshold.",
        )

    return HCPTargetingResult(
        brand_id=brand_id,
        brand_name=brand.name,
        country=country,
        data_status=HCPDataStatus.available,
        message=f"{len(targets)} HCP targets identified.",
        targets=targets,
    )
