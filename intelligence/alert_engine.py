from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.event_bus import Channel, publish_event
from core.logging import get_logger
from models.adverse_event import AdverseEventCandidate, AdverseEventReviewStatus
from models.alert import Alert, AlertSeverity, AlertType

logger = get_logger(__name__)


def create_alert(
    db: Session,
    alert_type: AlertType,
    severity: AlertSeverity,
    description: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    payload: Optional[dict] = None,
) -> Alert:
    alert = Alert(
        alert_type=alert_type,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        description=description,
        payload=payload,
        created_at=datetime.now(timezone.utc),
    )
    db.add(alert)
    db.flush()

    # Real-time push — fire-and-forget. The persisted Alert is the source of truth.
    publish_event(Channel.ALERTS, {
        "event": "alert.created",
        "id": alert.id,
        "alert_type": alert_type.value if hasattr(alert_type, "value") else str(alert_type),
        "severity": severity.value if hasattr(severity, "value") else str(severity),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "description": description,
        "created_at": alert.created_at.isoformat(),
        "payload": payload or {},
    })
    return alert


def process_mention_alerts(db: Session, mention_id: str, classification: dict) -> None:
    """
    Check a freshly classified mention for alert-triggering conditions.
    Called immediately after NLP processing of each mention.
    """
    risk_type = classification.get("risk_type", "none")
    is_ae = classification.get("is_adverse_event_candidate", False)
    is_promo = classification.get("is_prescription_promotion", False)

    if is_ae:
        _handle_adverse_event(db, mention_id, classification)

    # NB: keep the raw mention id out of the user-facing `description` — it's an
    # internal UUID, not something a pharmacist should read. It stays in `payload`
    # for traceability / drill-through.
    if risk_type == "shortage":
        create_alert(
            db,
            alert_type=AlertType.shortage,
            severity=AlertSeverity.high,
            description="Possible product shortage signalled in a monitored mention.",
            payload={"mention_id": mention_id},
        )

    if risk_type == "misinformation":
        create_alert(
            db,
            alert_type=AlertType.misinformation,
            severity=AlertSeverity.medium,
            description="Possible health misinformation detected in a monitored mention.",
            payload={"mention_id": mention_id},
        )

    if is_promo:
        create_alert(
            db,
            alert_type=AlertType.prescription_promotion,
            severity=AlertSeverity.high,
            description="Possible prescription-medicine promotion detected. Human review required.",
            payload={"mention_id": mention_id},
        )

    db.commit()


def _handle_adverse_event(db: Session, mention_id: str, classification: dict) -> None:
    existing = db.execute(
        select(AdverseEventCandidate).where(AdverseEventCandidate.mention_id == mention_id)
    ).scalar_one_or_none()

    if existing:
        return

    candidate = AdverseEventCandidate(
        mention_id=mention_id,
        product_id=classification.get("product_id"),
        description=classification.get("matched_patterns_str", "Adverse event patterns detected"),
        review_status=AdverseEventReviewStatus.pending,
        created_at=datetime.now(timezone.utc),
    )
    db.add(candidate)
    db.flush()

    create_alert(
        db,
        alert_type=AlertType.adverse_event,
        severity=AlertSeverity.critical,
        description="Adverse event candidate detected. Requires human pharmacovigilance review.",
        payload={"mention_id": mention_id, "candidate_id": candidate.id},
    )
    # Adverse-event candidates surface in the in-app review queue (the Alert row
    # above). Email/SMTP routing was removed — review happens in the dashboard.
