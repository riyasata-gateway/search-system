"""
GDPR Data Subject Rights — Arts. 15, 17, 20 EU GDPR

Implements:
- Right of Access (Art. 15): export all data associated with a pseudonymised author ID
- Right to Erasure (Art. 17): hard-delete personal references while preserving aggregates
- Right to Portability (Art. 20): export structured JSON for machine-readable portability

All operations are logged to the AuditLog for DPA accountability.

NOTE: PharmaWatch stores author IDs as HMAC-SHA256 pseudonyms (see core.security).
True identity resolution is NOT possible from the stored data (by design).
Data subjects must identify themselves via the original platform user ID
which is then re-pseudonymised to locate their records.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from core.security import pseudonymise_author
from models.mention import Mention, MentionClassification, MentionEntity
from models.user import AuditLog

logger = get_logger(__name__)


@dataclass
class DataSubjectExportRecord:
    mention_id: str
    source_type: Optional[str]
    country: Optional[str]
    language: Optional[str]
    published_at: Optional[str]
    sentiment: Optional[str]
    topic: Optional[str]
    risk_type: Optional[str]


async def handle_access_request(
    db: AsyncSession,
    raw_author_id: str,
    platform: str,
    requested_by_user_id: int,
    ip_address: str,
) -> List[DataSubjectExportRecord]:
    """
    GDPR Art. 15: Right of Access.
    Returns all mention records associated with the pseudonymised author.
    No raw text is returned — only metadata and classifications.
    """
    pseudo_id = pseudonymise_author(raw_author_id, platform)

    mentions = (
        await db.execute(
            select(Mention)
            .where(
                Mention.author_id_hash == pseudo_id,
                Mention.is_deleted == False,
            )
            .order_by(Mention.published_at.desc())
        )
    ).scalars().all()

    records = []
    for mention in mentions:
        classification = (
            await db.execute(
                select(MentionClassification).where(
                    MentionClassification.mention_id == mention.id
                )
            )
        ).scalar_one_or_none()

        records.append(DataSubjectExportRecord(
            mention_id=str(mention.id),
            source_type=mention.source_type,
            country=mention.country,
            language=mention.language,
            published_at=mention.published_at.isoformat() if mention.published_at else None,
            sentiment=str(classification.sentiment) if classification and classification.sentiment else None,
            topic=str(classification.topic) if classification and classification.topic else None,
            risk_type=str(classification.risk_type) if classification and classification.risk_type else None,
        ))

    await _write_audit_log(
        db,
        user_id=requested_by_user_id,
        action="gdpr_access_request",
        resource_type="mention",
        detail=f"pseudo_id={pseudo_id}, records_returned={len(records)}",
        ip_address=ip_address,
    )

    logger.info(
        "gdpr_access_request_handled",
        pseudo_id=pseudo_id,
        records=len(records),
        requested_by=requested_by_user_id,
    )
    return records


async def handle_erasure_request(
    db: AsyncSession,
    raw_author_id: str,
    platform: str,
    requested_by_user_id: int,
    ip_address: str,
) -> dict:
    """
    GDPR Art. 17: Right to Erasure ('right to be forgotten').
    Hard-deletes all mention text associated with a pseudonymised author.
    Aggregated trend signals and classification labels are RETAINED
    as they contain no personal data (recital 26 GDPR — anonymised data).

    Deletes: Mention text (clean_text set to NULL, is_deleted=True)
    Preserves: TrendSignal, MentionClassification aggregates, AuditLog of this action
    """
    pseudo_id = pseudonymise_author(raw_author_id, platform)

    result = await db.execute(
        update(Mention)
        .where(
            Mention.author_id_hash == pseudo_id,
            Mention.is_deleted == False,
        )
        .values(
            is_deleted=True,
            clean_text=None,
            author_id_hash=None,
        )
        .execution_options(synchronize_session="fetch")
    )
    erased_count = result.rowcount

    await _write_audit_log(
        db,
        user_id=requested_by_user_id,
        action="gdpr_erasure_request",
        resource_type="mention",
        detail=f"pseudo_id={pseudo_id}, erased_count={erased_count}",
        ip_address=ip_address,
    )
    await db.commit()

    logger.info(
        "gdpr_erasure_request_handled",
        pseudo_id=pseudo_id,
        erased_count=erased_count,
        requested_by=requested_by_user_id,
    )
    return {"pseudo_id": pseudo_id, "erased_count": erased_count}


async def handle_portability_request(
    db: AsyncSession,
    raw_author_id: str,
    platform: str,
    requested_by_user_id: int,
    ip_address: str,
) -> str:
    """
    GDPR Art. 20: Right to Data Portability.
    Returns machine-readable JSON export of all data associated with the author.
    No raw text is included — only metadata the data subject provided (platform pseudonym).
    """
    records = await handle_access_request(
        db, raw_author_id, platform, requested_by_user_id, ip_address
    )

    export = {
        "gdpr_portability_export": True,
        "platform": platform,
        "export_timestamp": datetime.now(timezone.utc).isoformat(),
        "data_controller": "PharmaWatch BV",
        "lawful_basis": "legitimate_interest",
        "note": (
            "Text content is not retained beyond the configured retention window. "
            "Only metadata and NLP-derived labels are included in this export."
        ),
        "records": [asdict(r) for r in records],
    }
    return json.dumps(export, indent=2, ensure_ascii=False)


async def _write_audit_log(
    db: AsyncSession,
    user_id: int,
    action: str,
    resource_type: str,
    detail: str,
    ip_address: str,
) -> None:
    log = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        detail=detail,
        ip_address=ip_address,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(log)
