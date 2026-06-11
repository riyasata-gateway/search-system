"""Intelligence endpoints — surfaces the analytic modules built on top of
the Mention / Brand / Product / PharmacySale tables.

Endpoints:

  GET  /api/v1/intelligence/bpi/{brand_id}            Brand Potential Index for one brand
  GET  /api/v1/intelligence/bpi                       Rank top brands by BPI
  GET  /api/v1/intelligence/momentum/{entity_type}/{entity_id}
  GET  /api/v1/intelligence/momentum                  Top movers
  GET  /api/v1/intelligence/anomalies                 Currently-anomalous entities
  GET  /api/v1/intelligence/lifecycle/{entity_type}/{entity_id}
  GET  /api/v1/intelligence/flywheel/acceptance       Flywheel acceptance rollups
  POST /api/v1/intelligence/flywheel/log              Log an action event
  GET  /api/v1/intelligence/counseling/{product_id}   OTC counseling tips
  GET  /api/v1/intelligence/substitutes/{product_id}  Substitution candidates

All endpoints require auth. Lab-only endpoints additionally enforce role.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, require_lab
from core.database import get_sync_db
from intelligence.anomaly import scan_anomalies
from intelligence.brand_potential_index import (
    compute_bpi, rank_bpi, compute_competitive_map, compute_competitor_moves,
)
from intelligence.campaign_pivot import suggest_pivots
from intelligence.counseling_tips import generate_counseling_tips
from intelligence.flywheel import acceptance_signals, log_action
from intelligence.hcp_targeting import rank_hcps
from intelligence.key_message import compute_key_messages
from intelligence.launch_readiness import compute_launch_readiness, rank_launch_readiness
from intelligence.lifecycle import classify_lifecycle
from intelligence.momentum import compute_momentum, rank_momentum
from intelligence.next_best_action import compute_next_best_actions
from intelligence.substitution import suggest_substitutes
from models.action_event import ActionDecision, ActionSubjectType
from models.user import User

router = APIRouter()


# ── Brand Potential Index ────────────────────────────────────────────────────
@router.get("/bpi/{brand_id}")
def get_bpi_for_brand(
    brand_id: int,
    country: Optional[str] = Query(None, max_length=2),
    # Default to a full year: BPI assesses brand *health* over history, and a
    # 90-day window leaves most of the corpus out (mentions skew older), which
    # made every brand collapse to the neutral 50 fallback. Matches the framework
    # tier's _BPI_WINDOW=365 in intelligence/search_intelligence.py.
    window_days: int = Query(365, ge=7, le=365),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    result = compute_bpi(db, brand_id, country=country, window_days=window_days)
    if result is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return result.to_bundle().to_dict()


@router.get("/bpi")
def list_bpi(
    country: Optional[str] = Query(None, max_length=2),
    # Default to a full year: BPI assesses brand *health* over history, and a
    # 90-day window leaves most of the corpus out (mentions skew older), which
    # made every brand collapse to the neutral 50 fallback. Matches the framework
    # tier's _BPI_WINDOW=365 in intelligence/search_intelligence.py.
    window_days: int = Query(365, ge=7, le=365),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_lab),
):
    return [r.to_bundle().to_dict() for r in rank_bpi(db, country=country, window_days=window_days, limit=limit)]


# ── Momentum ────────────────────────────────────────────────────────────────
@router.get("/momentum/{entity_type}/{entity_id}")
def momentum_one(
    entity_type: str,
    entity_id: int,
    country: Optional[str] = Query(None, max_length=2),
    period: str = Query("30d"),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    return compute_momentum(db, entity_type, entity_id, country=country, period=period).to_bundle().to_dict()


@router.get("/momentum")
def momentum_ranking(
    entity_type: str = Query("brand"),
    country: Optional[str] = Query(None, max_length=2),
    period: str = Query("30d"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    return [r.to_bundle().to_dict() for r in rank_momentum(db, entity_type=entity_type, country=country, period=period, limit=limit)]


# ── Anomaly ─────────────────────────────────────────────────────────────────
@router.get("/anomalies")
def anomalies(
    entity_type: str = Query("brand"),
    country: Optional[str] = Query(None, max_length=2),
    baseline_days: int = Query(30, ge=7, le=180),
    z_threshold: float = Query(2.0, ge=1.0, le=5.0),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    return [
        r.to_bundle().to_dict()
        for r in scan_anomalies(
            db,
            entity_type=entity_type,
            country=country,
            baseline_days=baseline_days,
            z_threshold=z_threshold,
        )
    ]


# ── Lifecycle ───────────────────────────────────────────────────────────────
@router.get("/lifecycle/{entity_type}/{entity_id}")
def lifecycle(
    entity_type: str,
    entity_id: int,
    country: Optional[str] = Query(None, max_length=2),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    return classify_lifecycle(db, entity_type, entity_id, country=country).to_bundle().to_dict()


# ── Flywheel ────────────────────────────────────────────────────────────────
class ActionLogRequest(BaseModel):
    subject_type: ActionSubjectType
    subject_id: str
    decision: ActionDecision
    context: Optional[dict] = None


@router.post("/flywheel/log")
def flywheel_log(
    payload: ActionLogRequest,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    evt = log_action(
        db,
        user_id=current_user.id,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        decision=payload.decision,
        context=payload.context,
    )
    return {"id": evt.id, "logged_at": evt.created_at.isoformat()}


@router.get("/flywheel/acceptance")
def flywheel_acceptance(
    subject_type: Optional[ActionSubjectType] = Query(None),
    bucket_key: str = Query("category"),
    # Default to a full year: BPI assesses brand *health* over history, and a
    # 90-day window leaves most of the corpus out (mentions skew older), which
    # made every brand collapse to the neutral 50 fallback. Matches the framework
    # tier's _BPI_WINDOW=365 in intelligence/search_intelligence.py.
    window_days: int = Query(365, ge=7, le=365),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    return [
        {
            "subject_type": s.subject_type,
            "bucket_key": s.bucket_key,
            "total": s.total,
            "positive": s.positive,
            "negative": s.negative,
            "acceptance_rate": s.acceptance_rate,
            "weight_multiplier": s.weight_multiplier,
        }
        for s in acceptance_signals(
            db, subject_type=subject_type, bucket_key=bucket_key, window_days=window_days
        )
    ]


# ── Pharmacist support ──────────────────────────────────────────────────────
@router.get("/counseling/{product_id}")
async def counseling(
    product_id: int,
    lang: str = Query("en"),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    out = await generate_counseling_tips(db, product_id, lang=lang)
    return {
        "product_name": out.product_name,
        "category_name": out.category_name,
        "counseling_tips": out.counseling_tips,
        "patient_qa": out.patient_qa,
        "refer_to_doctor_if": out.refer_to_doctor_if,
        "grounded_in": out.grounded_in,
        "model": out.model,
    }


# ── Semantic insight (RAG) over the ingested corpus ─────────────────────────
@router.get("/insight/{brand_id}")
def evidence_insight(
    brand_id: int,
    q: Optional[str] = Query(None, description="Question; blank → default summary"),
    lens: str = Query("evidence", description="evidence | voice | patient"),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_lab),
):
    """Grounded, cited insight from the ingested corpus via semantic retrieval +
    LLM synthesis. `lens` selects the source set (evidence=PubMed,
    voice=reviews, patient=forums)."""
    from intelligence import evidence_rag as rag
    sources = {"evidence": rag.EVIDENCE_SOURCES, "voice": rag.VOICE_SOURCES,
               "patient": rag.PATIENT_SOURCES}.get(lens, rag.EVIDENCE_SOURCES)
    return rag.answer(db, brand_id, query=q, source_types=sources)


# ── B9 — Trending topics ────────────────────────────────────────────────────
@router.get("/trending-topics/{brand_id}")
def trending_topics(
    brand_id: int,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_lab),
):
    """Topic mix for a brand with momentum: recent-window volume vs the prior
    window per topic, so the UI can show a sized topic-cloud with rising/falling
    direction. From the classified mention corpus."""
    from sqlalchemy import text as _text
    rows = db.execute(_text("""
        SELECT mc.topic,
               count(*) AS total,
               count(*) FILTER (WHERE m.published_at >= now() - interval '90 days') AS recent,
               count(*) FILTER (WHERE m.published_at >= now() - interval '180 days'
                                  AND m.published_at <  now() - interval '90 days') AS prior
        FROM mention_entities me
        JOIN mentions m ON m.id = me.mention_id
        JOIN mention_classifications mc ON mc.mention_id = m.id
        WHERE me.entity_type = 'brand' AND me.entity_id = :bid
          AND mc.topic IS NOT NULL AND mc.topic != 'general' AND m.is_deleted = false
        GROUP BY mc.topic ORDER BY total DESC
    """), {"bid": brand_id}).mappings().all()
    topics = []
    for r in rows:
        recent, prior = int(r["recent"] or 0), int(r["prior"] or 0)
        direction = "rising" if recent > prior else "falling" if recent < prior else "flat"
        topics.append({"topic": r["topic"], "total": int(r["total"]),
                       "recent": recent, "prior": prior, "direction": direction})
    return {"brand_id": brand_id, "topics": topics}


# ── B16 — Earned-media / press analysis lens ────────────────────────────────
@router.get("/press-timeline/{brand_id}")
def press_timeline(
    brand_id: int,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_lab),
):
    """Press/news coverage for a brand: monthly article volume + sentiment split,
    plus headline totals. Uses the (clean, brand-linked) rss/news mentions."""
    from sqlalchemy import text as _text
    rows = db.execute(_text("""
        SELECT to_char(date_trunc('month', m.published_at), 'YYYY-MM') AS month,
               count(*) AS articles,
               sum((mc.sentiment = 'positive')::int) AS positive,
               sum((mc.sentiment = 'negative')::int) AS negative,
               sum((mc.sentiment = 'neutral')::int)  AS neutral
        FROM mention_entities me
        JOIN mentions m ON m.id = me.mention_id
        LEFT JOIN mention_classifications mc ON mc.mention_id = m.id
        WHERE me.entity_type = 'brand' AND me.entity_id = :bid
          AND m.source_type IN ('rss', 'news') AND m.is_deleted = false
          AND m.published_at IS NOT NULL
        GROUP BY 1 ORDER BY 1
    """), {"bid": brand_id}).mappings().all()
    timeline = [{"month": r["month"], "articles": int(r["articles"]),
                 "positive": int(r["positive"] or 0), "negative": int(r["negative"] or 0),
                 "neutral": int(r["neutral"] or 0)} for r in rows]
    total = sum(t["articles"] for t in timeline)
    pos = sum(t["positive"] for t in timeline)
    neg = sum(t["negative"] for t in timeline)
    polar = pos + neg
    return {"brand_id": brand_id, "total_articles": total,
            "pos_pct": round(100 * pos / polar) if polar else None,
            "timeline": timeline}


# ── B11 — Brand Competitive Map ─────────────────────────────────────────────
@router.get("/competitive-map/{brand_id}")
def competitive_map(
    brand_id: int,
    country: Optional[str] = Query(None, max_length=2),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_lab),
):
    result = compute_competitive_map(db, brand_id, country=country)
    if result is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return result


# ── B10 — Competitor-movement detection ─────────────────────────────────────
@router.get("/competitor-moves/{brand_id}")
def competitor_moves(
    brand_id: int,
    country: Optional[str] = Query(None, max_length=2),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_lab),
):
    result = compute_competitor_moves(db, brand_id, country=country)
    if result is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return result


# ── Phase 2 — Brand-side prescriptive layer ─────────────────────────────────
@router.get("/launch-readiness/{brand_id}")
def launch_readiness_one(
    brand_id: int,
    country: Optional[str] = Query(None, max_length=2),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_lab),
):
    result = compute_launch_readiness(db, brand_id, country=country)
    if result is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return result.to_bundle().to_dict()


@router.get("/launch-readiness")
def launch_readiness_ranking(
    country: Optional[str] = Query(None, max_length=2),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_lab),
):
    return [
        r.to_bundle().to_dict()
        for r in rank_launch_readiness(db, country=country, limit=limit)
    ]


@router.get("/key-messages/{brand_id}")
def key_messages(
    brand_id: int,
    country: Optional[str] = Query(None, max_length=2),
    # Default to a full year: BPI assesses brand *health* over history, and a
    # 90-day window leaves most of the corpus out (mentions skew older), which
    # made every brand collapse to the neutral 50 fallback. Matches the framework
    # tier's _BPI_WINDOW=365 in intelligence/search_intelligence.py.
    window_days: int = Query(365, ge=7, le=365),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_lab),
):
    result = compute_key_messages(db, brand_id, country=country, window_days=window_days)
    if result is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return result.to_bundle().to_dict()


@router.get("/campaign-pivots/{brand_id}")
def campaign_pivots(
    brand_id: int,
    country: Optional[str] = Query(None, max_length=2),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_lab),
):
    result = suggest_pivots(db, brand_id, country=country)
    if result is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return result.to_bundle().to_dict()


@router.get("/hcp-targeting/{brand_id}")
def hcp_targeting(
    brand_id: int,
    country: Optional[str] = Query(None, max_length=2),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_lab),
):
    result = rank_hcps(db, brand_id, country=country, limit=limit)
    if result is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return result.to_bundle().to_dict()


@router.get("/next-best-action/{brand_id}")
def next_best_action(
    brand_id: int,
    country: Optional[str] = Query(None, max_length=2),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_lab),
):
    result = compute_next_best_actions(db, brand_id, country=country, limit=limit)
    if result is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return result.to_bundle().to_dict()


# ── Pharmacist support (continued) ──────────────────────────────────────────
@router.get("/substitutes/{product_id}")
def substitutes(
    product_id: int,
    pharmacy_id: Optional[int] = Query(None),
    reason: str = Query("shortage"),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    return [
        {
            "product_id": c.product_id,
            "product_name": c.product_name,
            "category_id": c.category_id,
            "in_stock_at_pharmacy": c.in_stock_at_pharmacy,
            "mention_volume_30d": c.mention_volume_30d,
            "flywheel_weight": c.flywheel_weight,
            "score": c.score,
            "reason": c.reason,
        }
        for c in suggest_substitutes(
            db, product_id, pharmacy_id=pharmacy_id, reason=reason, limit=limit
        )
    ]
