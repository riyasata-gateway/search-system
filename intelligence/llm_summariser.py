import asyncio
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

WEEKLY_SUMMARY_PROMPT = """You are a pharmaceutical brand intelligence analyst. 
Provide a concise executive summary (3-5 sentences) in English based on the data below.
Focus on: what changed this week, key drivers of change, competitor activity, and any risks.
Do NOT make medical claims. Do NOT recommend specific treatments or dosages.
Do NOT generate promotional content for prescription medicines.
Flag any adverse event mentions for human review — do not make conclusions on them.

Brand ID: {brand_id}
Period: {period_start} to {period_end}
Total mentions: {total_mentions}
Sentiment: {sentiment}
Top topics: {topics}
Top countries: {countries}
Risk mentions: {risk_count}
Adverse event candidates pending review: {ae_pending}

Write the executive summary:"""


async def generate_weekly_summary(
    brand_id: int,
    period_start: date,
    period_end: date,
    db: AsyncSession,
) -> str:
    """
    Generate LLM weekly executive summary for a brand.
    Uses Ollama/Mistral-7B-Instruct (self-hosted, EU-region).
    LLM is used for summarisation ONLY — not for medical decisions.
    """
    from sqlalchemy import text

    from models.mention import MentionClassification, MentionEntity, RiskType
    from models.mention import Mention
    from models.adverse_event import AdverseEventCandidate, AdverseEventReviewStatus

    entity_result = await db.execute(
        select(MentionEntity.mention_id).where(
            MentionEntity.entity_type == "brand",
            MentionEntity.entity_id == brand_id,
        )
    )
    mention_ids = [r[0] for r in entity_result.fetchall()]

    if not mention_ids:
        return "No mentions found for this brand in the selected period."

    sent_result = await db.execute(
        select(MentionClassification.sentiment, func.count().label("cnt"))
        .where(MentionClassification.mention_id.in_(mention_ids))
        .group_by(MentionClassification.sentiment)
    )
    sentiment_str = ", ".join(f"{r.sentiment}: {r.cnt}" for r in sent_result.fetchall() if r.sentiment)

    topic_result = await db.execute(
        select(MentionClassification.topic, func.count().label("cnt"))
        .where(MentionClassification.mention_id.in_(mention_ids))
        .group_by(MentionClassification.topic)
        .order_by(func.count().desc())
        .limit(5)
    )
    topics_str = ", ".join(f"{r.topic}: {r.cnt}" for r in topic_result.fetchall() if r.topic)

    country_result = await db.execute(
        select(Mention.country, func.count().label("cnt"))
        .where(Mention.id.in_(mention_ids), Mention.country.isnot(None))
        .group_by(Mention.country)
        .order_by(func.count().desc())
        .limit(5)
    )
    countries_str = ", ".join(f"{r.country}: {r.cnt}" for r in country_result.fetchall() if r.country)

    risk_result = await db.execute(
        select(func.count()).where(
            MentionClassification.mention_id.in_(mention_ids),
            MentionClassification.risk_type != RiskType.none,
        )
    )
    risk_count = risk_result.scalar() or 0

    ae_result = await db.execute(
        select(func.count()).where(
            AdverseEventCandidate.review_status == AdverseEventReviewStatus.pending
        )
    )
    ae_pending = ae_result.scalar() or 0

    prompt = WEEKLY_SUMMARY_PROMPT.format(
        brand_id=brand_id,
        period_start=period_start,
        period_end=period_end,
        total_mentions=len(mention_ids),
        sentiment=sentiment_str or "no data",
        topics=topics_str or "no data",
        countries=countries_str or "no data",
        risk_count=risk_count,
        ae_pending=ae_pending,
    )

    return await _call_ollama(prompt)


async def _call_ollama(prompt: str) -> str:
    """Generate the summary. Prefer the self-hosted Ollama model (keeps the
    aggregated context in-region); if Ollama is down or unconfigured, fall back
    to the configured OpenAI model so the summary still renders. Only aggregated,
    non-personal counts are sent to either backend."""
    # 1) Self-hosted Ollama first. Run the sync client off the event loop.
    try:
        import ollama as ollama_client
        response = await asyncio.to_thread(
            ollama_client.generate,
            model=settings.OLLAMA_MODEL,
            prompt=prompt,
            options={"temperature": 0.3, "num_predict": 300},
        )
        text = (response.get("response") or "").strip()
        if text:
            return text
    except Exception as exc:
        logger.warning("ollama_generate_failed", error=str(exc))

    # 2) Fallback: OpenAI (already used by AI search). Aggregated counts only.
    if settings.OPENAI_API_KEY:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            completion = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=300,
            )
            text = (completion.choices[0].message.content or "").strip()
            if text:
                return text
        except Exception as exc:
            logger.warning("openai_summary_failed", error=str(exc))

    return (
        "LLM summary unavailable: neither the self-hosted Ollama service nor the "
        "OpenAI fallback could be reached. Check OLLAMA_MODEL / OPENAI_API_KEY."
    )
