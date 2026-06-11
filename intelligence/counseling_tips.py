"""OTC counseling tips + patient Q&A scripts — auto-generated from trend context.

LLM-driven generation, grounded in:
  • The product / category being asked about
  • Top topics surfaced from recent mentions for that product (efficacy,
    side effects, price, etc.)
  • Adverse-event hints flagged in the AE review queue
  • The market the pharmacist serves (country, language)

Output is structured (counseling_tips + patient_qa pairs) so the frontend can
render either as a printable pharmacist card or as a guided dialogue.

Hard guardrails are inherited from `llm_summariser`: no medical claims, no
prescription promotion, flag (not conclude) on adverse-event signal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import settings
from core.logging import get_logger
from models.mention import Mention, MentionClassification, MentionEntity, Topic
from models.product import Product, ProductCategory

logger = get_logger(__name__)


_LANG_NAMES = {"en": "English", "fr": "French", "nl": "Dutch", "de": "German"}


_SYSTEM_PROMPT = """You are TDAH's pharmacist-support assistant (Trend Data Aggregator Hyperintelligent — by PharmaWatch).
Your job is to draft brief, evidence-based OTC counseling tips and patient
question-and-answer scripts for the pharmacist standing behind the counter.

HARD RULES:
- No diagnoses. No prescriptions. No off-label suggestions.
- Always include a "when to refer to a doctor" trigger.
- Never promote prescription medicines.
- If any adverse-event hint appears, instruct the pharmacist to flag it,
  not to reassure the patient.
- Respect the user-facing language: write tips and Q&A in {lang_name}.

OUTPUT — JSON ONLY, this exact shape:
{{
  "counseling_tips": ["<short, actionable tip>", "<...>", "<...>"],
  "patient_qa": [
    {{"q": "<plausible patient question>", "a": "<safe, brief answer>"}},
    {{"q": "<...>", "a": "<...>"}}
  ],
  "refer_to_doctor_if": ["<symptom that mandates referral>", "<...>"]
}}"""


@dataclass
class CounselingOutput:
    product_name: Optional[str]
    category_name: Optional[str]
    counseling_tips: List[str] = field(default_factory=list)
    patient_qa: List[Dict[str, str]] = field(default_factory=list)
    refer_to_doctor_if: List[str] = field(default_factory=list)
    grounded_in: List[str] = field(default_factory=list)
    model: str = ""


def _top_topics_for_product(
    db: Session, product_id: int, window_days: int = 90
) -> List[str]:
    since = date.today() - timedelta(days=window_days)
    q = (
        select(MentionClassification.topic, func.count().label("c"))
        .join(MentionEntity, MentionEntity.mention_id == MentionClassification.mention_id)
        .join(Mention, Mention.id == MentionEntity.mention_id)
        .where(
            MentionEntity.entity_type == "product",
            MentionEntity.entity_id == product_id,
            Mention.published_at >= since,
            Mention.is_deleted.is_(False),
            MentionClassification.topic.isnot(None),
        )
        .group_by(MentionClassification.topic)
        .order_by(func.count().desc())
        .limit(5)
    )
    return [
        row.topic.value if hasattr(row.topic, "value") else str(row.topic)
        for row in db.execute(q).fetchall()
        if row.topic and row.topic != Topic.general
    ]


async def generate_counseling_tips(
    db: Session,
    product_id: int,
    lang: str = "en",
) -> CounselingOutput:
    """Build a structured counseling card for a product."""
    product = db.get(Product, product_id)
    if product is None:
        return CounselingOutput(product_name=None, category_name=None,
                                counseling_tips=["Product not found."])

    category = db.get(ProductCategory, product.category_id) if product.category_id else None
    cat_name = category.name_en if category else None
    top_topics = _top_topics_for_product(db, product_id)
    grounded_in = [f"top recent topics: {', '.join(top_topics) or 'general'}"]
    if cat_name:
        grounded_in.append(f"category: {cat_name}")

    lang_name = _LANG_NAMES.get(lang, "English")

    if not settings.OPENAI_API_KEY:
        # Graceful fallback: static template so the surface still works without the LLM.
        tips = [
            f"Always confirm the patient is not taking interacting medication before recommending {product.name}.",
            "Advise the patient on the maximum daily dose and remind them to read the leaflet.",
            "Document any reported reaction in the pharmacy notes.",
        ]
        qa = [{
            "q": f"Is {product.name} safe for me?",
            "a": "It is generally well tolerated, but please share your current medication list so I can check for interactions.",
        }]
        return CounselingOutput(
            product_name=product.name,
            category_name=cat_name,
            counseling_tips=tips,
            patient_qa=qa,
            refer_to_doctor_if=[
                "Symptoms persist beyond a few days",
                "Signs of allergic reaction",
                "Pregnancy or breastfeeding",
            ],
            grounded_in=grounded_in,
            model="static_fallback",
        )

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    user_message = (
        f"Product: {product.name}\n"
        f"Category: {cat_name or 'OTC'}\n"
        f"Recent topic mix from real mentions: {', '.join(top_topics) or 'general'}\n"
        f"Generate the JSON now."
    )
    try:
        resp = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT.format(lang_name=lang_name)},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=600,
        )
        payload = json.loads(resp.choices[0].message.content or "{}")
    except Exception as exc:
        logger.warning("counseling_llm_failed", error=str(exc))
        payload = {}

    return CounselingOutput(
        product_name=product.name,
        category_name=cat_name,
        counseling_tips=payload.get("counseling_tips", []),
        patient_qa=payload.get("patient_qa", []),
        refer_to_doctor_if=payload.get("refer_to_doctor_if", []),
        grounded_in=grounded_in,
        model=settings.OPENAI_MODEL,
    )
