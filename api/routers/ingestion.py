from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_admin, require_pharmacist
from core.config import settings
from core.database import get_db
from models.user import User

router = APIRouter()

# source_type → Celery task name. Single source of truth for both the admin
# trigger and the per-topic "Collect now" flow.
TASK_MAP = {
    "google_trends": "ingestion.tasks.collect_google_trends",
    "reddit": "ingestion.tasks.collect_reddit",
    "rss": "ingestion.tasks.collect_rss_news",
    "forum": "ingestion.tasks.collect_forums",
    "youtube": "ingestion.tasks.collect_youtube",
}


class TriggerRequest(BaseModel):
    source_type: str
    search_topic_id: Optional[int] = None


class JobStatus(BaseModel):
    task_id: str
    status: str
    message: str


class TopicCollectResult(BaseModel):
    topic_id: int
    dispatched: dict  # source_type -> task_id
    skipped: list     # source_types not dispatched (disabled / unsupported)


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

    task_name = TASK_MAP.get(body.source_type)
    if not task_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown source_type: {body.source_type}",
        )

    task = celery_app.send_task(task_name, kwargs={"search_topic_id": body.search_topic_id})
    return JobStatus(task_id=task.id, status="queued", message=f"Ingestion task queued: {task_name}")


@router.post("/topics/{topic_id}/collect", response_model=TopicCollectResult)
async def collect_topic_now(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Self-service 'Collect now' — kick off ingestion for a topic's own enabled
    sources. The topic owner (or an admin) may run it; still DPIA-gated. Each
    collector receives the search_topic_id, so it uses the brand's keywords and
    the topic's markets/languages."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from models.search_topic import SearchTopic
    from models.user import UserRole

    if not settings.DPIA_PROCESSING_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="DPIA_PROCESSING_ENABLED is false. Complete the DPIA before enabling data collection.",
        )

    topic = (await db.execute(
        select(SearchTopic).where(SearchTopic.id == topic_id).options(selectinload(SearchTopic.sources))
    )).scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search topic not found")
    if current_user.role != UserRole.admin and topic.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your topic")

    from workers.celery_app import celery_app

    dispatched: dict = {}
    skipped: list = []
    for src in topic.sources:
        if not src.is_enabled:
            skipped.append(src.source_type)
            continue
        task_name = TASK_MAP.get(src.source_type)
        if not task_name:
            skipped.append(src.source_type)  # e.g. licensed_api — no collector
            continue
        task = celery_app.send_task(task_name, kwargs={"search_topic_id": topic.id})
        dispatched[src.source_type] = task.id

    return TopicCollectResult(topic_id=topic.id, dispatched=dispatched, skipped=skipped)


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
