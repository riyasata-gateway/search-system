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


def _extract_json(raw: str) -> dict:
    """Parse the model's JSON answer. JSON mode can't be forced alongside web
    search, so the web-search path may return the object wrapped in markdown
    fences or trailing prose — try a plain parse first, then fall back to the
    first balanced {...} block."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}


async def _call_model(client, messages, allow_web_search: bool, max_tokens: int = 900) -> str:
    """Call the model and return its raw text content, asking it to web-search
    when allowed & supported.

    Live web search is a built-in tool on the Responses API
    (`tools=[{"type": "web_search"}]`) — the legacy Chat Completions
    `web_search_options` only works on the `*-search-preview` models, so it 400s
    on general models like ours. If the Responses call fails for any reason we
    remember that and fall back to a plain JSON Chat Completions call, so AI mode
    degrades to the model's own knowledge rather than erroring."""
    global _WEB_SEARCH_SUPPORTED
    if allow_web_search and settings.AI_WEB_SEARCH and _WEB_SEARCH_SUPPORTED:
        try:
            # NB: the web_search tool is incompatible with forced JSON mode, so we
            # don't set a `text` format here and instead rely on the system prompt's
            # "respond ONLY with valid JSON" instruction + _extract_json() parsing.
            response = await asyncio.wait_for(
                client.responses.create(
                    model=settings.OPENAI_MODEL,
                    input=messages,
                    tools=[{"type": "web_search"}],
                ),
                timeout=45.0,
            )
            return response.output_text or "{}"
        except Exception as exc:
            _WEB_SEARCH_SUPPORTED = False
            logger.warning("ai_web_search_unsupported", error=str(exc))
    completion = await asyncio.wait_for(
        client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            max_completion_tokens=max_tokens,
            response_format={"type": "json_object"},
        ),
        timeout=25.0,
    )
    return completion.choices[0].message.content or "{}"

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
        raw = await _call_model(
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

    parsed = _extract_json(raw)

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


# ── Deep Insights: live deep-dive on the LATEST news for the query ───────────
class DeepInsight(BaseModel):
    topic: str
    detail: str
    category: str = "other"      # regulatory | safety | supply | market | clinical | other
    recency: Optional[str] = None


class DeepInsightSource(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None


class DeepFinding(BaseModel):
    """A single dated, sourced fact gathered while researching one angle."""
    angle: Optional[str] = None
    fact: str
    date: Optional[str] = None
    source_title: Optional[str] = None
    source_url: Optional[str] = None


class DeepInsightsResponse(BaseModel):
    query: str
    headline: str
    recommendation: Optional[str] = None   # the role's decision answer
    insights: List[DeepInsight]
    sources: List[DeepInsightSource]
    angles: List[str] = []                  # the research angles explored
    findings: List[DeepFinding] = []        # the raw evidence gathered, per angle
    model: str
    elapsed_ms: int
    role: str
    role_label: str
    web_search: bool


# Each role's PRIMARY decision the deep-dive must answer (not a generic summary).
_DEEP_FRAME = {
    "pharmacist": (
        "Answer the counter question: SHOULD the pharmacist order / stock / recommend this, or be cautious — and WHY? "
        "`recommendation` must be a clear verdict like 'Order — strong demand, no safety flags', "
        "'Order with caution', or 'Hold / propose a substitute'. Lead the insights with availability & shortages, "
        "safety signals, substitution and reimbursement angles from the latest news."),
    "brand_manager": (
        "Answer the brand-health question for the Belgian pharmacy channel: where is the brand WINNING vs LEAKING, "
        "and which SKU / segment / market is the problem? `recommendation` must be the single most important action "
        "(e.g. 'Defend share vs <competitor> launch', 'Fix the <region> distribution gap'). Lead with competitive moves, "
        "distribution/supply, pricing & reimbursement, and regulatory developments."),
    "marketing": (
        "Answer the demand-creation question: WHAT message, in WHICH region, around WHICH product, RIGHT NOW? "
        "`recommendation` must be a concrete timing/message call (e.g. 'Push the SPF range now — seasonal search spike'). "
        "Lead with demand shifts, search/seasonal moments, review-driven message themes and competitor activity."),
    "admin": "Give a balanced cross-functional read; `recommendation` = the single biggest takeaway.",
}


def _deep_plan_prompt(lang: str, role: str) -> str:
    """Phase 1 — decompose the query into distinct research angles for this role."""
    frame = _DEEP_FRAME.get(role, _DEEP_FRAME["admin"])
    return f"""You are planning a DEEP research dive for a {role_label(role)} on the
Belgian (primary) / French (secondary) pharmaceutical market.
{frame}

Break the user's query into FOUR distinct, high-value research angles that together
give a thorough, current picture for THIS role's decision. Choose the four most
decision-relevant of: regulatory / safety / supply & availability / competitive &
market / pricing & reimbursement / clinical & evidence / demand & seasonality.
Each angle is something to search the live web for the very latest on.

Respond with ONLY valid JSON (no markdown):
{{"angles": [{{"label": "short angle name", "query": "a focused search query for the latest info on this angle"}}]}}
Return EXACTLY four angles."""


def _deep_angle_prompt(lang: str, role: str, angle: str) -> str:
    """Phase 2 — research one angle live and return dated, sourced facts."""
    return f"""You are researching ONE angle of a deep dive for a {role_label(role)}
on the Belgian (primary) / French (secondary) pharmaceutical market.

ANGLE: "{angle}"

Use web search to find the MOST RECENT, concrete, specific facts (prioritise the
last 4–8 weeks). Prefer authoritative BE/FR/EU sources: FAGG/AFMPS, RIZIV/INAMI,
EMA / EudraVigilance, ANSM, BCFI/CBIP, pharmacy retailers & brand sites, and
reputable news. Be specific (names, numbers, dates) — no generic background.

Respond with ONLY valid JSON (no markdown):
{{"findings": [{{"fact": "one specific, dated fact", "date": "approx date",
  "source_title": "source name", "source_url": "https://…"}}]}}
Return 3–6 findings. Never fabricate a URL — omit it if you can't name one."""


def _deep_insights_prompt(lang: str, role: str) -> str:
    language = _LANG_NAMES.get(lang, "English")
    frame = _DEEP_FRAME.get(role, _DEEP_FRAME["admin"])
    return f"""You are a pharmaceutical news analyst for the Belgian / EU market,
briefing a {role_label(role)}. Use web search to DEEP-DIVE the LATEST news and
developments about the user's query — prioritise the most recent items (roughly
the last 4–8 weeks).

YOUR JOB IS TO ANSWER THIS PERSON'S DECISION, not to summarise generically:
{frame}
{lens_prompt(role)}

Be specific and current; cite what's actually happening. If you genuinely cannot
find recent news, say so honestly in `headline`/`recommendation` and return fewer
insights rather than padding with generic background.

Respond with ONLY valid JSON (no markdown fences), in {language} for `headline`,
`recommendation`, `topic` and `detail`:
{{
  "headline": "one-sentence read of the current situation",
  "recommendation": "the decision answer for this role — ONE or TWO sentences max, no markdown",
  "insights": [
    {{"topic": "short plain-text topic label (no markdown, no asterisks)",
      "detail": "1–2 sentences of the key, specific insight + why it matters to this role",
      "category": "regulatory|safety|supply|market|clinical|other",
      "recency": "approx date or timeframe if known"}}
  ],
  "sources": [{{"title": "source name", "url": "https://…"}}]
}}
Return 5–8 insights, most important first."""


@router.get("/deep-insights", response_model=DeepInsightsResponse)
async def deep_insights(
    q: str = Query(..., min_length=2, description="Brand, drug, or topic to deep-dive"),
    lang: str = Query("en"),
    role: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
):
    """Deep Insights — a live deep-dive on the latest news for the query, returned
    as ranked key-topic points (role-tailored). Independent of Live Search."""
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured.")
    from openai import AsyncOpenAI

    t0 = time.time()
    lens = resolve_role(current_user, role)
    lang = lang if lang in _LANG_NAMES else "en"
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    # ── A real multi-step deep dive (not a single call like normal AI mode) ──
    # Phase 1: decompose the query into role-specific research angles.
    # Phase 2: research each angle LIVE on the web, in parallel.
    # Phase 3: synthesise the gathered, dated, sourced findings into the answer.
    try:
        plan_raw = await _call_model(
            client,
            messages=[
                {"role": "system", "content": _deep_plan_prompt(lang, lens)},
                {"role": "user", "content": f'Query to deep-dive: "{q}"'},
            ],
            allow_web_search=False,
        )
        angles = [a for a in (_extract_json(plan_raw).get("angles") or [])
                  if isinstance(a, dict) and a.get("label")][:4]
        if not angles:
            angles = [{"label": "Latest developments", "query": q}]

        async def _research(angle: dict):
            label = str(angle.get("label"))
            try:
                raw = await _call_model(
                    client,
                    messages=[
                        {"role": "system",
                         "content": _deep_angle_prompt(lang, lens, label)},
                        {"role": "user", "content": str(angle.get("query") or q)},
                    ],
                    allow_web_search=True,
                )
                found = _extract_json(raw).get("findings") or []
                out = []
                for f in found:
                    if isinstance(f, dict) and f.get("fact"):
                        f["angle"] = label          # tag each fact with its angle
                        out.append(f)
                return out
            except Exception as exc:  # one angle failing must not sink the dive
                logger.warning("deep_angle_failed", angle=label, error=str(exc))
                return []

        angle_results = await asyncio.gather(*[_research(a) for a in angles])
        all_findings = [f for fl in angle_results for f in fl][:24]
        angle_labels = [str(a.get("label")) for a in angles]

        # Phase 3 — synthesise the role-tailored answer from the gathered evidence.
        synth_raw = await _call_model(
            client,
            messages=[
                {"role": "system", "content": _deep_insights_prompt(lang, lens)},
                {"role": "user", "content":
                    f'Query: "{q}"\n\nA multi-angle live deep dive gathered these dated, '
                    f'sourced findings — treat them as your evidence and cite their sources:\n'
                    f'{json.dumps(all_findings, ensure_ascii=False)[:7000]}\n\n'
                    f'Now synthesise the role-tailored deep analysis.'},
            ],
            allow_web_search=False,
            max_tokens=2400,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Deep Insights timed out. Please try again.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI model error: {str(exc)}")

    parsed = _extract_json(synth_raw)
    # Fall back to the researched findings' sources if synthesis omitted them.
    syn_sources = [s for s in (parsed.get("sources") or []) if isinstance(s, dict)]
    if not syn_sources:
        seen_u, syn_sources = set(), []
        for f in all_findings:
            u = f.get("source_url")
            if u and u not in seen_u:
                seen_u.add(u)
                syn_sources.append({"title": f.get("source_title"), "url": u})
    parsed["sources"] = syn_sources
    insights = []
    for it in (parsed.get("insights") or [])[:8]:
        if isinstance(it, dict) and it.get("topic"):
            insights.append(DeepInsight(
                topic=str(it.get("topic")).replace("*", "").strip()[:160],
                detail=str(it.get("detail") or "")[:600],
                category=str(it.get("category") or "other").lower(),
                recency=(str(it["recency"])[:60] if it.get("recency") else None),
            ))
    sources = [DeepInsightSource(title=(s.get("title") or None), url=(s.get("url") or None))
               for s in (parsed.get("sources") or []) if isinstance(s, dict)][:10]
    headline = parsed.get("headline") or (
        "Latest developments from the deep dive:" if (insights or all_findings)
        else "No recent news found for this query.")
    rec = parsed.get("recommendation")
    findings = [DeepFinding(
        angle=(f.get("angle") or None),
        fact=str(f.get("fact"))[:400],
        date=(str(f["date"])[:40] if f.get("date") else None),
        source_title=(f.get("source_title") or None),
        source_url=(f.get("source_url") or None),
    ) for f in all_findings if isinstance(f, dict) and f.get("fact")]
    return DeepInsightsResponse(
        query=q, headline=str(headline)[:400],
        recommendation=(str(rec)[:500] if rec else None),
        insights=insights, sources=sources,
        angles=angle_labels, findings=findings,
        model=settings.OPENAI_MODEL, elapsed_ms=int((time.time() - t0) * 1000),
        role=lens, role_label=role_label(lens),
        web_search=bool(settings.AI_WEB_SEARCH and _WEB_SEARCH_SUPPORTED),
    )


# ── PR24: Belgium + France product-search demographic insights ───────────────
# Allowlists of Belgian and French regions/provinces (folded) — region insights
# are filtered to these so the feature can NEVER surface a region outside the two
# markets PharmaWatch tracks (Belgium primary, France secondary).
_BELGIAN_REGIONS = {
    "flanders", "vlaanderen", "flandre", "wallonia", "wallonie", "wallonie",
    "brussels", "brussels-capital", "brussels capital", "bruxelles", "brussel",
    "antwerp", "antwerpen", "anvers", "east flanders", "oost-vlaanderen", "flandre orientale",
    "west flanders", "west-vlaanderen", "flandre occidentale", "flemish brabant",
    "vlaams-brabant", "brabant flamand", "limburg", "limbourg", "hainaut", "henegouwen",
    "liege", "liège", "luik", "luxembourg", "namur", "namen", "walloon brabant",
    "brabant wallon", "waals-brabant",
}

# French metropolitan regions + major metros (folded). "luxembourg" is intentionally
# only in the Belgian set (the province) — the country is never a region here.
_FRENCH_REGIONS = {
    "ile-de-france", "île-de-france", "ile de france", "paris",
    "auvergne-rhone-alpes", "auvergne-rhône-alpes", "rhone-alpes", "rhône-alpes", "lyon",
    "hauts-de-france", "nouvelle-aquitaine", "bordeaux",
    "occitanie", "toulouse", "grand est", "grand-est", "strasbourg",
    "provence-alpes-cote d'azur", "provence-alpes-côte d'azur", "paca", "marseille", "nice",
    "pays de la loire", "pays-de-la-loire", "nantes", "normandy", "normandie",
    "brittany", "bretagne", "rennes", "bourgogne-franche-comte", "bourgogne-franche-comté",
    "centre-val de loire", "centre-val-de-loire", "corsica", "corse", "lille",
}

# Country tags so the UI/PDF can show which market each region belongs to.
_FR_COUNTRY_TOKENS = ("france", "(fr)", "french")
_BE_COUNTRY_TOKENS = ("belgium", "belgique", "belgië", "(be)", "belgian")


def _region_country(label: str) -> Optional[str]:
    """Classify a region label as Belgium / France, or None if it matches neither
    allowlist. Explicit country tokens in the label win first."""
    s = (label or "").strip().lower()
    if any(tok in s for tok in _BE_COUNTRY_TOKENS) and not any(tok in s for tok in _FR_COUNTRY_TOKENS):
        return "Belgium"
    if any(tok in s for tok in _FR_COUNTRY_TOKENS):
        return "France"
    if any(tok in s for tok in _BELGIAN_REGIONS):
        return "Belgium"
    if any(tok in s for tok in _FRENCH_REGIONS):
        return "France"
    return None


def _is_allowed_region(label: str) -> bool:
    return _region_country(label) is not None


class Pr24Item(BaseModel):
    label: str
    share: Optional[float] = None     # 0–100 relative interest index within the pillar
    note: str = ""                    # one-line behavioural pattern


class Pr24Source(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None


class Pr24Pillar(BaseModel):
    items: List[Pr24Item]
    sources: List[Pr24Source]         # references the model relied on for this pillar


class Pr24Response(BaseModel):
    query: str
    summary: str
    gender: Pr24Pillar
    age_group: Pr24Pillar
    region: Pr24Pillar                # Belgian + French regions
    model: str
    elapsed_ms: int
    web_search: bool


def _pr24_prompt(lang: str, role: str) -> str:
    language = _LANG_NAMES.get(lang, "English")
    return f"""You are a consumer market-research analyst specialising in BELGIUM and FRANCE. For the
user's product or category query, analyse INTERNET PRODUCT-SEARCH BEHAVIOUR across three pillars:
GENDER, AGE GROUP, and REGION (Belgium and France only).

STRICT GEOGRAPHY — non-negotiable:
- Belgium and France ONLY. Every insight is about Belgian or French internet users searching for
  this product/category. NEVER mention any country or region outside Belgium and France.
- Belgian regions: the three regions (Flanders, Wallonia, Brussels-Capital) and/or Belgian
  provinces (Antwerp, East/West Flanders, Flemish Brabant, Limburg, Hainaut, Liège, Luxembourg,
  Namur, Walloon Brabant).
- French regions: metropolitan regions (Île-de-France, Auvergne-Rhône-Alpes, Hauts-de-France,
  Nouvelle-Aquitaine, Occitanie, Grand Est, Provence-Alpes-Côte d'Azur, Pays de la Loire,
  Normandy, Brittany, Bourgogne-Franche-Comté, Centre-Val de Loire, Corsica) and/or major metros
  (Paris, Lyon, Marseille).
- In the REGION pillar, give a MIX across both markets — at least one Belgian and one French
  region — and ALWAYS append the country to each region label, e.g. "Flanders (Belgium)",
  "Île-de-France (France)".

For EACH pillar, give the 2–4 segments most likely to be searching for this product/category:
- `label`: the segment (gender "Female"/"Male"; age "25–34"; region "Flanders (Belgium)")
- `share`: an approximate RELATIVE interest index 0–100 within that pillar (need not sum to 100)
- `note`: ONE line on the meaningful search-behaviour pattern (what/why), market-specific

EACH pillar also returns a `sources` array — the concrete references you relied on for that
pillar (title + URL). Use web search for Belgian and French signal; NEVER fabricate a URL — omit
a source you can't actually name. Write `summary` and every `note` in {language}.

Respond ONLY with valid JSON (no markdown):
{{
  "summary": "one-line read of who searches for this in Belgium and France",
  "gender":    {{"items": [{{"label": "Female", "share": 70, "note": "..."}}], "sources": [{{"title": "...", "url": "https://..."}}]}},
  "age_group": {{"items": [{{"label": "25–34", "share": 60, "note": "..."}}], "sources": [{{"title": "...", "url": "https://..."}}]}},
  "region":    {{"items": [{{"label": "Flanders (Belgium)", "share": 55, "note": "..."}}, {{"label": "Île-de-France (France)", "share": 50, "note": "..."}}], "sources": [{{"title": "...", "url": "https://..."}}]}}
}}"""


@router.get("/pr24", response_model=Pr24Response)
async def pr24_insights(
    q: str = Query(..., min_length=2, description="Product or category to profile for Belgium & France"),
    lang: str = Query("en"),
    role: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
):
    """PR24 — Belgium + France internet product-search insights for a query, grouped
    under three pillars: gender, age group, and region (Belgian and French)."""
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured.")
    from openai import AsyncOpenAI

    t0 = time.time()
    lens = resolve_role(current_user, role)
    lang = lang if lang in _LANG_NAMES else "en"
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    try:
        raw = await _call_model(
            client,
            messages=[
                {"role": "system", "content": _pr24_prompt(lang, lens)},
                {"role": "user", "content": f'Product/category query: "{q}" — profile Belgian search behaviour.'},
            ],
            allow_web_search=True,
            max_tokens=1100,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="PR24 insights timed out. Please try again.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI model error: {str(exc)}")

    parsed = _extract_json(raw)

    def _pillar(key: str, region_only: bool = False, cap: int = 4) -> Pr24Pillar:
        block = parsed.get(key) or {}
        # Tolerate either the new {items, sources} shape or a bare items list.
        raw_items = block.get("items") if isinstance(block, dict) else block
        raw_sources = block.get("sources") if isinstance(block, dict) else []
        items: List[Pr24Item] = []
        for it in (raw_items or []):
            if not isinstance(it, dict) or not it.get("label"):
                continue
            label = str(it["label"]).strip()[:60]
            if region_only and not _is_allowed_region(label):
                continue   # defensive: drop any region outside Belgium/France
            share = it.get("share")
            try:
                share = max(0.0, min(100.0, float(share))) if share is not None else None
            except (TypeError, ValueError):
                share = None
            items.append(Pr24Item(label=label, share=share, note=str(it.get("note") or "")[:200]))
        sources = [
            Pr24Source(title=(str(s.get("title")) if s.get("title") else None),
                       url=(str(s.get("url")) if s.get("url") else None))
            for s in (raw_sources or []) if isinstance(s, dict) and (s.get("url") or s.get("title"))
        ][:6]
        return Pr24Pillar(items=items[:cap], sources=sources)

    return Pr24Response(
        query=q,
        summary=str(parsed.get("summary") or f"Belgium & France search-behaviour profile for '{q}'.")[:400],
        gender=_pillar("gender"),
        age_group=_pillar("age_group"),
        region=_pillar("region", region_only=True, cap=6),
        model=settings.OPENAI_MODEL,
        elapsed_ms=int((time.time() - t0) * 1000),
        web_search=bool(settings.AI_WEB_SEARCH and _WEB_SEARCH_SUPPORTED),
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
