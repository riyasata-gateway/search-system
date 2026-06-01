"""
AI-powered search — an INDEPENDENT research mode.

  GET /api/v1/search/ai?q=<query>   — the model researches the query itself
                                       (its own up-to-date knowledge + live web
                                       search when available) and returns a
                                       role-tailored synthesis with its own cited
                                       sources.

AI mode is deliberately standalone: it is NOT fed Live Search results and never
shares context with the live connectors. Live Search and AI Mode are two distinct
answers to the same query — one is a real-time connector fan-out, the other is an
independent LLM analysis. (The old POST "Ask AI about these results" bridge was
removed so the two modes stay fully independent.)
"""
import asyncio
import json
import time
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel

from api.dependencies import get_current_user
from core.config import settings
from core.logging import get_logger
from core.role_lens import lens_prompt, resolve_role, role_label
from core.search_metrics import SearchIntelligence
from intelligence.search_intelligence import build_search_intelligence, flatten_for_db
from core.search_audit import log_search_query
from models.search_audit import SearchMode
from models.user import User
from processing.query_expansion import expand_query

router = APIRouter()
logger = get_logger(__name__)

_WEB_SEARCH_SUPPORTED = True


async def _call_model(client, messages, allow_web_search: bool):
    """Call the chat model, asking it to web-search when allowed & supported.

    If the model/deployment doesn't accept `web_search_options` (or it clashes
    with JSON mode), we remember that and fall back to the plain JSON call — so
    AI mode degrades to the model's own knowledge rather than erroring."""
    global _WEB_SEARCH_SUPPORTED
    base = dict(
        model=settings.OPENAI_MODEL,
        messages=messages,
        max_completion_tokens=900,
        response_format={"type": "json_object"},
    )
    if allow_web_search and settings.AI_WEB_SEARCH and _WEB_SEARCH_SUPPORTED:
        try:
            return await asyncio.wait_for(
                client.chat.completions.create(**base, web_search_options={}),
                timeout=35.0,
            )
        except Exception as exc:
            _WEB_SEARCH_SUPPORTED = False
            logger.warning("ai_web_search_unsupported", error=str(exc))
    return await asyncio.wait_for(
        client.chat.completions.create(**base),
        timeout=25.0,
    )

# `sentiment_summary` stays in English so the frontend badge styling keeps working;
# narrative fields (answer, key_points, disclaimer) are rendered in the user's locale.
_LANG_NAMES = {
    "en": "English",
    "fr": "French (français)",
    "nl": "Dutch (Nederlands)",
    "de": "German (Deutsch)",
}


def _build_system_prompt(lang: str, role: str = "admin") -> str:
    lang_name = _LANG_NAMES.get(lang, "English")

    # AI mode is independent: no sources are pre-supplied, the model does its own
    # research. (Live Search is the connector-grounded mode; we keep them distinct.)
    grounding = (
        "RESEARCH & GROUNDING — VERY IMPORTANT:\n"
        "No sources are pre-supplied. Research this yourself using your own "
        "up-to-date knowledge of the Belgium (primary) and France (secondary) "
        "market for the queried product/brand — and live web search if you have "
        "that capability. Prefer recent, local, authoritative signal.\n"
        "- Populate the `sources` array with the concrete references you relied "
        "on (title + URL). Cite them inline in `answer`/`key_points` as [1],[2]… "
        "matching the order of the `sources` array.\n"
        "- Be explicit about uncertainty; for safety- or availability-critical "
        "claims, recommend verifying against official BE/FR sources (FAGG/AFMPS, "
        "ANSM, EudraVigilance). Never fabricate a URL — omit a source you can't name."
    )

    return f"""You are TDAH AI (Trend Data Aggregator Hyperintelligent — by PharmaWatch), an expert pharmaceutical intelligence assistant for the EU market (Belgium primary, France secondary). You turn a query about a drug/brand into intelligence about what is happening in that country regarding that product.

{lens_prompt(role)}

MAKE IT ACTIONABLE FOR THIS ROLE'S WORK:
- Frame the answer so it directly helps the reader do their job (per the audience lens above).
- At least one key point must be a concrete next step / recommended action this role can take in their work area.
- Lead with what matters most to this role; treat the rest as supporting context.

When answering:
- Provide a clear, factual summary (2-4 sentences)
- Highlight notable sentiment patterns, risk signals, or trends
- List 3-5 concise key points (include the action point above)
- State the overall sentiment (Positive / Mixed / Negative / Neutral)
- Always note that this is informational only and not medical advice
- Keep language professional and EU-pharma appropriate

LANGUAGE — VERY IMPORTANT:
- Write the `answer`, every entry in `key_points`, and the `disclaimer` in {lang_name}.
- The `sentiment_summary` field MUST stay in English: exactly one of "Positive", "Mixed", "Negative", "Neutral".

{grounding}

Respond ONLY with valid JSON in this exact structure:
{{
  "answer": "<main summary paragraph with [n] citations, in {lang_name}>",
  "key_points": ["<point with [n] citations, in {lang_name}>", "<point>", "<point>"],
  "sentiment_summary": "Positive|Mixed|Negative|Neutral",
  "disclaimer": "<one-sentence medical/regulatory disclaimer, in {lang_name}>",
  "sources": [{{"title": "<short source title>", "url": "<https://...>"}}]
}}"""


class AISearchSource(BaseModel):
    source_type: str
    source_url: Optional[str] = None
    text: str
    sentiment: str
    published_at: Optional[str] = None
    country: Optional[str] = None


class AISearchResponse(BaseModel):
    query: str
    answer: str
    key_points: List[str]
    sentiment_summary: str
    disclaimer: str
    sources: List[AISearchSource]
    expanded_terms: List[str]
    model: str
    elapsed_ms: int
    role: str
    role_label: str
    metrics: Optional[SearchIntelligence] = None


async def _synthesise(
    query: str,
    expanded_terms: List[str],
    t0: float,
    lang: str = "en",
    role: str = "admin",
    user_id: Optional[int] = None,
    background_tasks: Optional[BackgroundTasks] = None,
) -> AISearchResponse:
    """Independent LLM synthesis — the model researches the query itself; no
    connector sources are supplied (that's Live Search's job)."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    lang = lang if lang in _LANG_NAMES else "en"

    expansion_note = ""
    if len(expanded_terms) > 1:
        expansion_note = (
            f"\n\nNote: '{query}' was expanded across EU brand variants: "
            f"{', '.join(expanded_terms)}."
        )

    user_message = f'Analyse this pharmaceutical query: "{query}"{expansion_note}'

    try:
        completion = await _call_model(
            client,
            messages=[
                {"role": "system", "content": _build_system_prompt(lang, role)},
                {"role": "user", "content": user_message},
            ],
            # AI mode always researches independently → allow web search.
            allow_web_search=True,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="AI model timed out. Please try again.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI model error: {str(exc)}")

    raw = completion.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}

    # Surface the references the model itself cited (from its own knowledge / web
    # search) as the source cards.
    sources: List[dict] = []
    for ms in (parsed.get("sources") or [])[:8]:
        if not isinstance(ms, dict):
            continue
        url = ms.get("url") or ms.get("source_url")
        title = ms.get("title") or ms.get("name") or url
        if not (url or title):
            continue
        sources.append({
            "source_type": "web",
            "source_url": url,
            "text": title or url,
            "sentiment": "neutral",
            "country": ms.get("country"),
        })

    answer = parsed.get("answer", f"No AI summary available for '{query}'.")
    key_points = parsed.get("key_points", [])
    sentiment_summary = parsed.get("sentiment_summary", "Neutral")
    disclaimer = parsed.get(
        "disclaimer",
        "This is for informational purposes only and does not constitute medical advice.",
    )

    source_models = [
        AISearchSource(
            source_type=r.get("source_type", "src"),
            source_url=r.get("source_url"),
            text=r.get("text", ""),
            sentiment=r.get("sentiment", "neutral"),
            published_at=r.get("published_at"),
            country=r.get("country"),
        )
        for r in sources[:8]
    ]

    elapsed_ms = int((time.time() - t0) * 1000)

    # Per-search DIA intelligence — framework tier (BPI/momentum/… for the resolved
    # brand) is corpus-based and independent of the AI text; snapshot tier is thin
    # here (the model's own cited sources). Computed off-thread (sync DB modules).
    si = await asyncio.get_event_loop().run_in_executor(
        None,
        build_search_intelligence,
        [
            {
                "source_type": s.get("source_type"),
                "country": s.get("country"),
                "language": s.get("language"),
                "published_at": s.get("published_at"),
                "sentiment": s.get("sentiment"),
                "topic": s.get("topic"),
                "risk_type": s.get("risk_type"),
                "engagement": None,
            }
            for s in sources[:8]
        ],
        role, query, expanded_terms, "ai",
    )

    if background_tasks is not None:
        background_tasks.add_task(
            log_search_query,
            mode=SearchMode.ai,
            q=query,
            user_id=user_id,
            lang=lang,
            role=role,
            expanded_terms=expanded_terms,
            metrics=flatten_for_db(si),
            results=[
                {
                    "rank": i,
                    "source_type": s.get("source_type"),
                    "source_url": s.get("source_url"),
                    "snippet": s.get("text"),
                    "sentiment": s.get("sentiment"),
                    "country": s.get("country"),
                    "language": s.get("language"),
                }
                for i, s in enumerate(sources[:8], start=1)
            ],
            ai_answer={
                "answer": answer,
                "key_points": key_points,
                "sentiment_summary": sentiment_summary,
                "disclaimer": disclaimer,
                "grounding_sources": [
                    {
                        "ref": i,
                        "source_type": s.get("source_type"),
                        "source_url": s.get("source_url"),
                        "snippet": (s.get("text") or "")[:300],
                    }
                    for i, s in enumerate(sources[:8], start=1)
                ],
            },
            ai_model=settings.OPENAI_MODEL,
            elapsed_ms=elapsed_ms,
        )

    return AISearchResponse(
        query=query,
        answer=answer,
        key_points=key_points,
        sentiment_summary=sentiment_summary,
        disclaimer=disclaimer,
        sources=source_models,
        expanded_terms=expanded_terms,
        model=settings.OPENAI_MODEL,
        elapsed_ms=elapsed_ms,
        role=role,
        role_label=role_label(role),
        metrics=si,
    )


@router.get("/ai", response_model=AISearchResponse)
async def ai_search(
    background_tasks: BackgroundTasks,
    q: str = Query(..., min_length=2, description="Brand, drug, or topic to analyse"),
    lang: str = Query("en", description="Output language: en, fr, nl, de"),
    role: Optional[str] = Query(None, description="Role lens: pharmacist, marketing, brand_manager, admin"),
    current_user: User = Depends(get_current_user),
):
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API key not configured. Set OPENAI_API_KEY in your .env file.",
        )

    t0 = time.time()
    lens = resolve_role(current_user, role)
    expanded = expand_query(q.strip(), max_terms=8)
    # AI mode researches the query itself (own knowledge + web search) and returns
    # the references it used. It is fully independent of Live Search.
    return await _synthesise(
        q, expanded, t0, lang=lang, role=lens,
        user_id=current_user.id, background_tasks=background_tasks,
    )
