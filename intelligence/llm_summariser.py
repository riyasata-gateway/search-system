import asyncio
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

WEEKLY_SUMMARY_PROMPT = """You are a pharmaceutical brand-intelligence analyst writing an executive brief for a {role_label}.
Use ONLY the structured facts below — never invent numbers, competitors, or events. No medical claims, no treatment/dosage advice. Flag adverse-event signals for human review without drawing conclusions.

Write 3–5 sentences of flowing prose (not a list), in this order:
1. WHAT CHANGED — lead with the biggest movement vs the prior period (use the deltas).
2. WHY — the drivers (top topics / notable items provided).
3. COMPETITIVE POSITION — the brand's share-of-voice rank within its category.
4. SAFETY — any new risk/adverse-event signal (flag for review); if none, state signals are clear.
5. ACTION — end with ONE concrete recommended action that follows from these facts.

=== FACTS — {brand} ({category}) · {period_start} → {period_end} (vs prior {span} days) ===
Mentions: {cur_m} this period vs {prior_m} prior ({m_delta})
Pharmacy reviews: {cur_r} vs {prior_r} ({r_delta})
Sentiment this period: {pos} positive / {neu} neutral / {neg} negative ({pos_share}% positive, {pos_delta})
Top topics this period: {topics}
Share of Voice in {category}: {sov_share}% — rank #{sov_rank} of {sov_n}; category leader: {sov_leader}
Risk / adverse-event mentions this period: {risk_count}{ae_note}
Notable recent items: {events}

Executive brief:"""

_ROLE_LABELS = {"brand_manager": "brand manager", "marketing": "marketing lead",
                "pharmacist": "pharmacist", "admin": "cross-functional lead"}


def _delta(cur: int, prior: int, span: int) -> str:
    if prior == 0:
        return "no prior-period activity" if cur == 0 else f"new (none in prior {span}d)"
    pct = round(100 * (cur - prior) / prior)
    arrow = "▲" if pct > 0 else "▼" if pct < 0 else "■"
    return f"{arrow} {pct:+d}% vs prior {span}d"


async def generate_weekly_summary(
    brand_id: int,
    period_start: date,
    period_end: date,
    db: AsyncSession,
    role: str = "brand_manager",
) -> str:
    """Decision-grade executive brief: WHAT CHANGED (period-over-period deltas) →
    WHY (drivers) → COMPETITIVE POSITION (SoV rank) → SAFETY → one ACTION.

    Feeds the LLM *computed facts with comparisons* (not raw totals), so the brief
    reports real movement and a recommendation instead of paraphrasing counts.
    Summarisation only — never a medical decision. Uses OpenAI.
    """
    from datetime import timedelta
    from sqlalchemy import text
    from core.framework_catalog import category_family

    span = (period_end - period_start).days or 30
    prior_start = period_start - timedelta(days=span)

    brow = (await db.execute(text("SELECT name, category FROM brands WHERE id=:b"),
                             {"b": brand_id})).first()
    if not brow:
        return "Brand not found."
    bname, bcat = brow[0], brow[1] or "its category"

    async def _count(d0, d1, sources_only=False):
        q = ("SELECT count(*) FROM mention_entities me JOIN mentions m ON m.id=me.mention_id "
             "WHERE me.entity_type='brand' AND me.entity_id=:b AND m.is_deleted=false "
             "AND m.published_at >= :d0 AND m.published_at < :d1")
        if sources_only:
            q += " AND m.source_type IN ('farmaline','medimarket')"
        return (await db.execute(text(q), {"b": brand_id, "d0": d0, "d1": d1})).scalar() or 0

    cur_m = await _count(period_start, period_end)
    prior_m = await _count(prior_start, period_start)
    cur_r = await _count(period_start, period_end, sources_only=True)
    prior_r = await _count(prior_start, period_start, sources_only=True)

    if cur_m == 0 and prior_m == 0:
        return (f"No mentions linked to {bname} in {period_start} → {period_end} or the prior "
                f"{span} days — nothing to report this period.")

    # Sentiment split this period (+ prior positive-share for the delta)
    async def _sent(d0, d1):
        rows = (await db.execute(text(
            "SELECT mc.sentiment, count(*) c FROM mention_classifications mc "
            "JOIN mention_entities me ON me.mention_id=mc.mention_id "
            "JOIN mentions m ON m.id=mc.mention_id "
            "WHERE me.entity_type='brand' AND me.entity_id=:b AND m.is_deleted=false "
            "AND m.published_at >= :d0 AND m.published_at < :d1 GROUP BY mc.sentiment"),
            {"b": brand_id, "d0": d0, "d1": d1})).all()
        d = {str(s).split(".")[-1].lower(): c for s, c in rows}
        return d.get("positive", 0), d.get("neutral", 0), d.get("negative", 0)

    pos, neu, neg = await _sent(period_start, period_end)
    tot_cls = pos + neu + neg
    pos_share = round(100 * pos / tot_cls) if tot_cls else 0
    p_pos, p_neu, p_neg = await _sent(prior_start, period_start)
    p_tot = p_pos + p_neu + p_neg
    p_share = round(100 * p_pos / p_tot) if p_tot else 0
    pos_delta = (f"{pos_share - p_share:+d} pts vs prior {span}d" if p_tot else "no prior baseline")

    # Top topics this period
    trows = (await db.execute(text(
        "SELECT mc.topic, count(*) c FROM mention_classifications mc "
        "JOIN mention_entities me ON me.mention_id=mc.mention_id "
        "JOIN mentions m ON m.id=mc.mention_id "
        "WHERE me.entity_type='brand' AND me.entity_id=:b AND m.is_deleted=false "
        "AND m.published_at >= :d0 AND m.published_at < :d1 AND mc.topic IS NOT NULL "
        "GROUP BY mc.topic ORDER BY c DESC LIMIT 4"),
        {"b": brand_id, "d0": period_start, "d1": period_end})).all()
    topics = ", ".join(f"{str(t).split('.')[-1]} ({c})" for t, c in trows) or "no classified topics"

    # Risk / adverse-event signal this period
    risk_count = (await db.execute(text(
        "SELECT count(*) FROM mention_classifications mc "
        "JOIN mention_entities me ON me.mention_id=mc.mention_id "
        "JOIN mentions m ON m.id=mc.mention_id "
        "WHERE me.entity_type='brand' AND me.entity_id=:b AND m.is_deleted=false "
        "AND m.published_at >= :d0 AND m.published_at < :d1 "
        "AND mc.risk_type <> 'none'"),
        {"b": brand_id, "d0": period_start, "d1": period_end})).scalar() or 0
    ae_count = (await db.execute(text(
        "SELECT count(*) FROM mention_classifications mc "
        "JOIN mention_entities me ON me.mention_id=mc.mention_id "
        "JOIN mentions m ON m.id=mc.mention_id "
        "WHERE me.entity_type='brand' AND me.entity_id=:b AND m.is_deleted=false "
        "AND m.published_at >= :d0 AND m.published_at < :d1 "
        "AND mc.is_adverse_event_candidate=true"),
        {"b": brand_id, "d0": period_start, "d1": period_end})).scalar() or 0
    ae_note = f" — {ae_count} flagged as adverse-event candidates (pending human review)" if ae_count else ""

    # Notable recent items (news / clinical commentary), newest first
    erows = (await db.execute(text(
        "SELECT left(coalesce(m.clean_text, m.raw_text), 130) FROM mention_entities me "
        "JOIN mentions m ON m.id=me.mention_id "
        "WHERE me.entity_type='brand' AND me.entity_id=:b AND m.is_deleted=false "
        "AND m.source_type IN ('rss','news','bcfi','clinical_trials') "
        "AND m.published_at >= :d0 AND m.published_at < :d1 "
        "ORDER BY m.published_at DESC NULLS LAST LIMIT 3"),
        {"b": brand_id, "d0": period_start, "d1": period_end})).all()
    events = " | ".join((e[0] or "").strip().replace("\n", " ") for e in erows) or "none in feed"

    # Share of Voice within the category family, this period + rank
    fam = category_family(bcat)
    crows = (await db.execute(text("SELECT id, name, category FROM brands WHERE category IS NOT NULL"))).all()
    peers = [(bid, nm) for bid, nm, cat in crows if category_family(cat) == fam]
    counts = {}
    for pid, pnm in peers:
        counts[pnm] = await _count_for(db, pid, period_start, period_end)
    total_voice = sum(counts.values()) or 1
    sov_share = round(100 * counts.get(bname, 0) / total_voice)
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    sov_n = len(ranked)
    sov_rank = next((i + 1 for i, (nm, _) in enumerate(ranked) if nm == bname), sov_n)
    sov_leader = ranked[0][0] if ranked else bname
    if sov_n <= 1:
        sov_share, sov_rank, sov_leader = 100, 1, "sole tracked brand"

    prompt = WEEKLY_SUMMARY_PROMPT.format(
        role_label=_ROLE_LABELS.get(role, "brand manager"),
        brand=bname, category=bcat, period_start=period_start, period_end=period_end, span=span,
        cur_m=cur_m, prior_m=prior_m, m_delta=_delta(cur_m, prior_m, span),
        cur_r=cur_r, prior_r=prior_r, r_delta=_delta(cur_r, prior_r, span),
        pos=pos, neu=neu, neg=neg, pos_share=pos_share, pos_delta=pos_delta,
        topics=topics, sov_share=sov_share, sov_rank=sov_rank, sov_n=sov_n, sov_leader=sov_leader,
        risk_count=risk_count, ae_note=ae_note, events=events,
    )
    return await _generate(prompt)


async def _count_for(db: AsyncSession, brand_id: int, d0: date, d1: date) -> int:
    from sqlalchemy import text
    return (await db.execute(text(
        "SELECT count(*) FROM mention_entities me JOIN mentions m ON m.id=me.mention_id "
        "WHERE me.entity_type='brand' AND me.entity_id=:b AND m.is_deleted=false "
        "AND m.published_at >= :d0 AND m.published_at < :d1"),
        {"b": brand_id, "d0": d0, "d1": d1})).scalar() or 0


async def _generate(prompt: str) -> str:
    """Generate the summary via OpenAI (same backend as AI search). Only
    aggregated, non-personal counts are sent. Capped at 20s so the dashboard
    never hangs."""
    if not settings.OPENAI_API_KEY:
        return "LLM summary unavailable: OPENAI_API_KEY is not configured."
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        completion = await asyncio.wait_for(
            client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=300,
            ),
            timeout=20.0,
        )
        return (completion.choices[0].message.content or "").strip() or "Summary unavailable."
    except asyncio.TimeoutError:
        logger.warning("openai_summary_timeout")
        return "Summary timed out — please retry."
    except Exception as exc:
        logger.warning("openai_summary_failed", error=str(exc))
        return "Summary unavailable — the model could not be reached."
