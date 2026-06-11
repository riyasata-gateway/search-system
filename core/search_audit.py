"""Search audit helper — persists every /search/* call to Postgres.

Writes are scheduled via FastAPI BackgroundTasks so they never delay the user
response. Uses a fresh sync session per write since the audit row is short-lived
and we don't want to hold an async request-scoped session past the response.
"""
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from core.database import SyncSessionLocal
from core.logging import get_logger
from models.search_audit import AIAnswer, SearchMode, SearchQuery, SearchResult
from models.search_metrics import SearchMetric

logger = get_logger(__name__)


def log_search_query(
    *,
    mode: SearchMode,
    q: str,
    user_id: Optional[int],
    lang: Optional[str] = None,
    role: Optional[str] = None,
    sources_requested: Optional[list] = None,
    expanded_terms: Optional[list] = None,
    filters: Optional[dict] = None,
    results: Optional[List[dict]] = None,
    ai_answer: Optional[dict] = None,
    ai_model: Optional[str] = None,
    elapsed_ms: Optional[int] = None,
    metrics: Optional[dict] = None,
) -> Optional[str]:
    """Persist a single search call + its results.

    `results` shape (each dict): {rank, source_type, source_url, snippet,
        sentiment, topic, risk_type, score, mention_id, country, language,
        published_at}.

    `ai_answer` shape: {answer, key_points, sentiment_summary, disclaimer,
        grounding_sources}.

    Returns the new query id, or None on failure (failure must never break the
    response path).
    """
    try:
        query_id = str(uuid4())
        with SyncSessionLocal() as db:
            sq = SearchQuery(
                id=query_id,
                user_id=user_id,
                mode=mode,
                q=q[:512],
                lang=lang,
                role=role,
                sources_requested=sources_requested,
                expanded_terms=expanded_terms,
                filters=filters,
                total_results=len(results) if results else 0,
                elapsed_ms=elapsed_ms,
                created_at=datetime.now(timezone.utc),
            )
            db.add(sq)

            for r in (results or []):
                db.add(SearchResult(
                    query_id=query_id,
                    rank=r.get("rank", 0),
                    source_type=r.get("source_type"),
                    source_url=r.get("source_url"),
                    snippet=(r.get("snippet") or "")[:8000] or None,
                    sentiment=r.get("sentiment"),
                    topic=r.get("topic"),
                    risk_type=r.get("risk_type"),
                    score=r.get("score"),
                    mention_id=r.get("mention_id"),
                    country=r.get("country"),
                    language=r.get("language"),
                    published_at=r.get("published_at"),
                ))

            if ai_answer:
                db.add(AIAnswer(
                    query_id=query_id,
                    model=ai_model or "unknown",
                    answer=ai_answer.get("answer", ""),
                    key_points=ai_answer.get("key_points"),
                    sentiment_summary=ai_answer.get("sentiment_summary"),
                    disclaimer=ai_answer.get("disclaimer"),
                    grounding_sources=ai_answer.get("grounding_sources"),
                    created_at=datetime.now(timezone.utc),
                ))

            if metrics:
                db.add(SearchMetric(query_id=query_id, **metrics))

            db.commit()
            return query_id
    except Exception as exc:
        logger.warning("search_audit_write_failed", error=str(exc), mode=mode.value)
        return None