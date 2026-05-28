from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.dependencies import get_current_user, write_audit_log
from core.database import get_db
from models.search_topic import SearchTopic, SearchTopicCompetitor, SearchTopicSource, TimeWindow
from models.user import User

router = APIRouter()


class SearchTopicSourceIn(BaseModel):
    source_type: str
    is_enabled: bool = True


class SearchTopicIn(BaseModel):
    name: str
    brand_id: Optional[int] = None
    category_id: Optional[int] = None
    countries: List[str]
    languages: List[str]
    time_window: TimeWindow = TimeWindow.days_30
    competitor_brand_ids: List[int] = []
    sources: List[SearchTopicSourceIn] = []


class SearchTopicOut(BaseModel):
    id: int
    name: str
    brand_id: Optional[int]
    category_id: Optional[int]
    countries: List[str]
    languages: List[str]
    time_window: TimeWindow
    is_active: bool

    class Config:
        from_attributes = True


@router.get("/", response_model=List[SearchTopicOut])
async def list_search_topics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SearchTopic).where(SearchTopic.user_id == current_user.id)
    )
    return result.scalars().all()


@router.post("/", response_model=SearchTopicOut, status_code=status.HTTP_201_CREATED)
async def create_search_topic(
    request: Request,
    body: SearchTopicIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    topic = SearchTopic(
        user_id=current_user.id,
        name=body.name,
        brand_id=body.brand_id,
        category_id=body.category_id,
        countries=body.countries,
        languages=body.languages,
        time_window=body.time_window,
    )
    db.add(topic)
    await db.flush()

    for brand_id in body.competitor_brand_ids:
        db.add(SearchTopicCompetitor(search_topic_id=topic.id, brand_id=brand_id))

    for src in body.sources:
        db.add(SearchTopicSource(
            search_topic_id=topic.id,
            source_type=src.source_type,
            is_enabled=src.is_enabled,
        ))

    await write_audit_log(db, current_user.id, "create", "search_topic", str(topic.id), request.client.host)
    await db.commit()
    await db.refresh(topic)
    return topic


@router.put("/{topic_id}", response_model=SearchTopicOut)
async def update_search_topic(
    request: Request,
    topic_id: int,
    body: SearchTopicIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SearchTopic).where(
            SearchTopic.id == topic_id,
            SearchTopic.user_id == current_user.id,
        ).options(selectinload(SearchTopic.competitors), selectinload(SearchTopic.sources))
    )
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search topic not found")

    topic.name = body.name
    topic.brand_id = body.brand_id
    topic.category_id = body.category_id
    topic.countries = body.countries
    topic.languages = body.languages
    topic.time_window = body.time_window

    for c in topic.competitors:
        await db.delete(c)
    for s in topic.sources:
        await db.delete(s)
    await db.flush()

    for brand_id in body.competitor_brand_ids:
        db.add(SearchTopicCompetitor(search_topic_id=topic.id, brand_id=brand_id))
    for src in body.sources:
        db.add(SearchTopicSource(search_topic_id=topic.id, source_type=src.source_type, is_enabled=src.is_enabled))

    await write_audit_log(db, current_user.id, "update", "search_topic", str(topic_id), request.client.host)
    await db.commit()
    await db.refresh(topic)
    return topic


@router.delete("/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_search_topic(
    request: Request,
    topic_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SearchTopic).where(SearchTopic.id == topic_id, SearchTopic.user_id == current_user.id)
    )
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search topic not found")
    await db.delete(topic)
    await write_audit_log(db, current_user.id, "delete", "search_topic", str(topic_id), request.client.host)
    await db.commit()
