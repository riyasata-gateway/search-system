"""Semantic search — reads the Qdrant vector store and joins back to the
mentions corpus for full payload + classification. This is the read-side that
was missing: embeddings were being written on every ingestion but never queried.
"""
import time
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from core.config import settings
from core.database import get_db
from core.role_lens import grounding_sort_key, resolve_role, role_label
from core.search_metrics import SearchIntelligence
from intelligence.search_intelligence import build_search_intelligence, flatten_for_db
from core.search_audit import log_search_query
from models.mention import Mention, MentionClassification
from models.search_audit import SearchMode
from models.user import User
from processing.embeddings import embed_text, _get_qdrant

router = APIRouter()


class SemanticHit(BaseModel):
    mention_id: str
    score: float
    source_type: Optional[str]
    source_url: Optional[str]
    country: Optional[str]
    language: Optional[str]
    published_at: Optional[datetime]
    clean_text: Optional[str]
    sentiment: Optional[str]
    topic: Optional[str]
    risk_type: Optional[str]


class SemanticSearchResponse(BaseModel):
    query: str
    total: int
    results: List[SemanticHit]
    elapsed_ms: int
    role: str
    role_label: str
    metrics: Optional[SearchIntelligence] = None


@router.get("/semantic", response_model=SemanticSearchResponse)
async def semantic_search_endpoint(
    background_tasks: BackgroundTasks,
    q: str = Query(..., min_length=2, description="Free-text query"),
    top_k: int = Query(20, ge=1, le=100),
    language: Optional[str] = Query(None, description="ISO 639-1: fr, nl, en, de"),
    country: Optional[str] = Query(None, description="ISO 3166-1 alpha-2: BE, FR, …"),
    role: Optional[str] = Query(None, description="Role lens: pharmacist, marketing, brand_manager, admin"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    t0 = time.time()
    lens = resolve_role(current_user, role)
    lens_label = role_label(lens)
    vector = embed_text(q.strip())
    if vector is None:
        return SemanticSearchResponse(query=q, total=0, results=[], elapsed_ms=0,
                                      role=lens, role_label=lens_label)

    # Qdrant payload filter — narrows recall server-side instead of post-filtering.
    qdrant_filter = None
    must = []
    if language:
        must.append({"key": "language", "match": {"value": language}})
    if country:
        must.append({"key": "country", "match": {"value": country}})
    if must:
        qdrant_filter = {"must": must}

    client = _get_qdrant()
    hits = client.search(
        collection_name=settings.QDRANT_COLLECTION,
        query_vector=vector,
        limit=top_k,
        query_filter=qdrant_filter,
    )
    if not hits:
        return SemanticSearchResponse(query=q, total=0, results=[],
                                      elapsed_ms=int((time.time() - t0) * 1000),
                                      role=lens, role_label=lens_label)

    id_to_score = {h.payload.get("mention_id"): float(h.score) for h in hits if h.payload}
    mention_ids = [mid for mid in id_to_score if mid]

    if not mention_ids:
        return SemanticSearchResponse(query=q, total=0, results=[],
                                      elapsed_ms=int((time.time() - t0) * 1000),
                                      role=lens, role_label=lens_label)

    rows = (await db.execute(
        select(Mention, MentionClassification)
        .outerjoin(MentionClassification,
                   MentionClassification.mention_id == Mention.id)
        .where(Mention.id.in_(mention_ids), Mention.is_deleted == False)
    )).all()

    results: List[SemanticHit] = []
    for mention, cls in rows:
        results.append(SemanticHit(
            mention_id=mention.id,
            score=id_to_score.get(mention.id, 0.0),
            source_type=mention.source_type,
            source_url=mention.source_url,
            country=mention.country,
            language=mention.language,
            published_at=mention.published_at,
            clean_text=mention.clean_text,
            sentiment=cls.sentiment.value if cls and cls.sentiment else None,
            topic=cls.topic.value if cls and cls.topic else None,
            risk_type=cls.risk_type.value if cls and cls.risk_type else None,
        ))

    # Role-aware ordering WITHOUT a multiplicative score. Cosine similarity is the
    # real search relevance, so it stays primary — but we band it (round to 0.05)
    # so near-equally-relevant hits form a group, and within each band the role's
    # source/topic priority tier decides order. A pharmacist's safety/supply
    # sources surface first among similarly-relevant results; semantic quality is
    # never sacrificed to the lens.
    def _sem_key(r):
        band = -round(r.score / 0.05) * 0.05  # descending similarity bands
        return (band, *grounding_sort_key(lens, r.source_type, r.topic))
    results.sort(key=_sem_key)
    elapsed_ms = int((time.time() - t0) * 1000)

    import asyncio
    si = await asyncio.get_event_loop().run_in_executor(
        None,
        build_search_intelligence,
        [
            {
                "source_type": r.source_type,
                "country": r.country,
                "language": r.language,
                "published_at": r.published_at,
                "sentiment": r.sentiment,
                "topic": r.topic,
                "risk_type": r.risk_type,
                "engagement": None,   # semantic corpus has no engagement signal
            }
            for r in results
        ],
        lens, q, [], "semantic",
    )

    background_tasks.add_task(
        log_search_query,
        mode=SearchMode.semantic,
        q=q,
        user_id=current_user.id,
        role=lens,
        filters={"language": language, "country": country, "top_k": top_k},
        metrics=flatten_for_db(si),
        results=[
            {
                "rank": i,
                "source_type": r.source_type,
                "source_url": r.source_url,
                "snippet": r.clean_text,
                "sentiment": r.sentiment,
                "topic": r.topic,
                "risk_type": r.risk_type,
                "score": r.score,
                "mention_id": r.mention_id,
                "country": r.country,
                "language": r.language,
                "published_at": r.published_at,
            }
            for i, r in enumerate(results, start=1)
        ],
        elapsed_ms=elapsed_ms,
    )

    return SemanticSearchResponse(
        query=q,
        total=len(results),
        results=results,
        elapsed_ms=elapsed_ms,
        role=lens,
        role_label=lens_label,
        metrics=si,
    )