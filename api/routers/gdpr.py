from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_admin, write_audit_log
from core.database import get_db
from gdpr.data_subject_requests import (
    handle_access_request,
    handle_erasure_request,
    handle_portability_request,
)
from models.user import User

router = APIRouter()


class DataSubjectRequestIn(BaseModel):
    raw_author_id: str
    platform: str


@router.post("/access", summary="GDPR Art. 15 — Right of Access")
async def gdpr_access(
    body: DataSubjectRequestIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    records = await handle_access_request(
        db=db,
        raw_author_id=body.raw_author_id,
        platform=body.platform,
        requested_by_user_id=current_user.id,
        ip_address=request.client.host if request.client else "unknown",
    )
    return {"count": len(records), "records": records}


@router.post("/erasure", summary="GDPR Art. 17 — Right to Erasure")
async def gdpr_erasure(
    body: DataSubjectRequestIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await handle_erasure_request(
        db=db,
        raw_author_id=body.raw_author_id,
        platform=body.platform,
        requested_by_user_id=current_user.id,
        ip_address=request.client.host if request.client else "unknown",
    )
    return result


@router.post("/portability", summary="GDPR Art. 20 — Right to Data Portability")
async def gdpr_portability(
    body: DataSubjectRequestIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    from fastapi.responses import Response
    json_export = await handle_portability_request(
        db=db,
        raw_author_id=body.raw_author_id,
        platform=body.platform,
        requested_by_user_id=current_user.id,
        ip_address=request.client.host if request.client else "unknown",
    )
    return Response(
        content=json_export,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=gdpr_export.json"},
    )
