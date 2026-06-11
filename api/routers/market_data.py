"""Market data + de-identified Rx import endpoints.

CSV-only ingestion because the upstream feeds (IQVIA, GERS, IMS, hospital
Rx extracts) arrive as periodic file drops, not APIs. Two routes:

  POST /api/v1/market-data/imports/market-data
       header: X-Source: iqvia|gers|ims|other
       body: CSV with columns:
         product_id, brand_id, country, region, period, period_start,
         period_end, units, revenue_eur, market_share_pct

  POST /api/v1/market-data/imports/prescriptions
       body: CSV with columns:
         product_id, brand_id, country, region, hcp_id, hcp_specialty,
         patient_age_band, patient_sex, rx_date, units, is_new_to_brand

`hcp_id` is HMAC-pseudonymised on ingest — the raw identifier is never
persisted. `retention_expires_at` is set per `MENTION_RETENTION_DAYS`
so the existing GDPR sweep ages out rows alongside Mentions.

Both endpoints are admin-only and produce a `MarketDataImport` audit row.
"""
import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from api.dependencies import require_admin
from core.config import settings
from core.database import get_sync_db
from core.logging import get_logger
from core.security import pseudonymise_author
from models.market_data import (
    MarketData, MarketDataImport, MarketDataPeriod, MarketDataSource,
    PrescriptionEvent,
)
from models.user import User

logger = get_logger(__name__)

router = APIRouter()


# ── shared helpers ──────────────────────────────────────────────────────────
def _parse_date(value: str) -> Optional[date]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _int(value: str) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "t"}


def _csv_rows(file: UploadFile):
    """Decode the upload as UTF-8 CSV. Returns (rows, errors)."""
    raw = file.file.read()
    if not raw:
        return [], ["empty file"]
    try:
        text = raw.decode("utf-8-sig")  # tolerate BOM
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except UnicodeDecodeError as exc:
            return [], [f"decode failed: {exc}"]
    reader = csv.DictReader(io.StringIO(text))
    return list(reader), []


# ── market data import ─────────────────────────────────────────────────────
@router.post("/imports/market-data")
async def import_market_data(
    source: MarketDataSource = Form(...),
    notes: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_admin),
):
    rows, decode_errors = _csv_rows(file)
    if decode_errors:
        raise HTTPException(status_code=400, detail="; ".join(decode_errors))

    saved = 0
    rejected = 0
    for r in rows:
        country = (r.get("country") or "").strip().upper()
        period_raw = (r.get("period") or "monthly").strip().lower()
        period_start = _parse_date(r.get("period_start", ""))
        period_end = _parse_date(r.get("period_end", "")) or period_start
        if not country or len(country) != 2 or period_start is None:
            rejected += 1
            continue
        try:
            period = MarketDataPeriod(period_raw)
        except ValueError:
            rejected += 1
            continue

        db.add(MarketData(
            source=source,
            product_id=_int(r.get("product_id", "")),
            brand_id=_int(r.get("brand_id", "")),
            country=country,
            region=(r.get("region") or "").strip() or None,
            period=period,
            period_start=period_start,
            period_end=period_end or period_start,
            units=_int(r.get("units", "")),
            revenue_eur=_float(r.get("revenue_eur", "")),
            market_share_pct=_float(r.get("market_share_pct", "")),
            source_filename=file.filename,
        ))
        saved += 1

    audit = MarketDataImport(
        uploaded_by=current_user.id,
        source=source,
        kind="market_data",
        filename=file.filename or "—",
        row_count=saved,
        rejected_count=rejected,
        uploaded_at=datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(audit)
    db.commit()
    logger.info("market_data_import", saved=saved, rejected=rejected, source=source.value,
                user=current_user.id)
    return {
        "saved": saved,
        "rejected": rejected,
        "import_id": audit.id,
        "filename": file.filename,
    }


# ── prescription events import ──────────────────────────────────────────────
@router.post("/imports/prescriptions")
async def import_prescriptions(
    source: MarketDataSource = Form(...),
    notes: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_admin),
):
    rows, decode_errors = _csv_rows(file)
    if decode_errors:
        raise HTTPException(status_code=400, detail="; ".join(decode_errors))

    retention = None
    if settings.MENTION_RETENTION_DAYS:
        retention = datetime.now(timezone.utc) + timedelta(days=settings.MENTION_RETENTION_DAYS)

    saved = 0
    rejected = 0
    for r in rows:
        rx_date = _parse_date(r.get("rx_date", ""))
        country = (r.get("country") or "").strip().upper()
        if rx_date is None or not country or len(country) != 2:
            rejected += 1
            continue
        raw_hcp = (r.get("hcp_id") or "").strip()
        hcp_hash = pseudonymise_author(raw_hcp, platform=source.value) if raw_hcp else None

        db.add(PrescriptionEvent(
            product_id=_int(r.get("product_id", "")),
            brand_id=_int(r.get("brand_id", "")),
            country=country,
            region=(r.get("region") or "").strip() or None,
            hcp_id_hash=hcp_hash,
            hcp_specialty=(r.get("hcp_specialty") or "").strip() or None,
            patient_age_band=(r.get("patient_age_band") or "").strip() or None,
            patient_sex=(r.get("patient_sex") or "").strip()[:1] or None,
            rx_date=rx_date,
            units=_int(r.get("units", "1")) or 1,
            is_new_to_brand=_bool(r.get("is_new_to_brand", "")),
            collected_at=datetime.now(timezone.utc),
            retention_expires_at=retention,
            source_filename=file.filename,
        ))
        saved += 1

    audit = MarketDataImport(
        uploaded_by=current_user.id,
        source=source,
        kind="prescription_event",
        filename=file.filename or "—",
        row_count=saved,
        rejected_count=rejected,
        uploaded_at=datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(audit)
    db.commit()
    logger.info("rx_import", saved=saved, rejected=rejected, user=current_user.id)
    return {
        "saved": saved,
        "rejected": rejected,
        "import_id": audit.id,
        "filename": file.filename,
    }


@router.get("/imports")
def list_imports(
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_admin),
):
    from sqlalchemy import select
    rows = db.execute(
        select(MarketDataImport).order_by(MarketDataImport.uploaded_at.desc()).limit(50)
    ).scalars().all()
    return [
        {
            "id": r.id,
            "uploaded_by": r.uploaded_by,
            "source": r.source.value,
            "kind": r.kind,
            "filename": r.filename,
            "row_count": r.row_count,
            "rejected_count": r.rejected_count,
            "uploaded_at": r.uploaded_at.isoformat(),
            "notes": r.notes,
        }
        for r in rows
    ]
