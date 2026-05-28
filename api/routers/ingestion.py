from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_admin, require_pharmacist
from core.config import settings
from core.database import get_db
from models.user import User

router = APIRouter()


class TriggerRequest(BaseModel):
    source_type: str
    search_topic_id: Optional[int] = None


class JobStatus(BaseModel):
    task_id: str
    status: str
    message: str


@router.post("/trigger", response_model=JobStatus)
async def trigger_ingestion(
    body: TriggerRequest,
    current_user: User = Depends(require_admin),
):
    if not settings.DPIA_PROCESSING_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="DPIA_PROCESSING_ENABLED is false. Complete the DPIA before enabling data collection.",
        )

    from workers.celery_app import celery_app

    task_map = {
        "google_trends": "ingestion.tasks.collect_google_trends",
        "reddit": "ingestion.tasks.collect_reddit",
        "rss": "ingestion.tasks.collect_rss_news",
        "forum": "ingestion.tasks.collect_forums",
        "youtube": "ingestion.tasks.collect_youtube",
    }
    task_name = task_map.get(body.source_type)
    if not task_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown source_type: {body.source_type}",
        )

    task = celery_app.send_task(task_name, kwargs={"search_topic_id": body.search_topic_id})
    return JobStatus(task_id=task.id, status="queued", message=f"Ingestion task queued: {task_name}")


@router.post("/pharmacy/import", response_model=JobStatus)
async def import_pharmacy_data(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_pharmacist),
):
    if current_user.pharmacy_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not linked to a pharmacy",
        )
    if file.content_type not in (
        "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV and XLSX files are accepted",
        )

    content = await file.read()
    from workers.celery_app import celery_app
    task = celery_app.send_task(
        "ingestion.tasks.import_pharmacy_file",
        kwargs={
            "pharmacy_id": current_user.pharmacy_id,
            "filename": file.filename,
            "content": content.decode("latin-1"),
        },
    )
    return JobStatus(task_id=task.id, status="queued", message="Pharmacy file import queued")


@router.get("/status/{task_id}", response_model=JobStatus)
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    from workers.celery_app import celery_app
    result = celery_app.AsyncResult(task_id)
    return JobStatus(
        task_id=task_id,
        status=result.state,
        message=str(result.info) if result.info else "",
    )
