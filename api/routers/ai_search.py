"""
AI-powered search — fetches live context then synthesises an answer via OpenAI.
Endpoints:
  GET  /api/v1/search/ai?q=<query>            — synthesises from fresh news fetch
  POST /api/v1/search/ai                      — accepts pre-fetched context (used
                                                by the "Ask AI about these results"
                                                bridge from Live Search)
"""
import asyncio
import json
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.dependencies import get_current_user
from core.config import settings
from models.user import User
from processing.query_expansion import expand_query

router = APIRouter()

# `sentiment_summary` stays in English so the frontend badge styling keeps working;
# narrative fields (answer, key_points, disclaimer) are rendered in the user's locale.
_LANG_NAMES = {
    "en": "English",
    "fr": "French (français)",
    "nl": "Dutch (Nederlands)",
    "de": "German (Deutsch)",
}


def _build_system_prompt(lang: str) -> str:
    lang_name = _LANG_NAMES.get(lang, "English")
    return f"""You are TDAH AI (Trend Data Aggregator Hyperintelligent — by PharmaWatch), an expert pharmaceutical intelligence assistant for the EU market (Belgium and France, Phase 1). You help pharmacists and pharmaceutical lab users understand brand sentiment, side effect signals, pricing trends, and drug availability based on real-world data.

When answering queries about drugs or pharmaceutical brands:
- Provide a clear, factual summary (2-4 sentences)
- Highlight any notable sentiment patterns, risk signals, or trends
- List 3-5 concise key points
- State the overall sentiment (Positive / Mixed / Negative / Neutral)
- Always note that this is informational only and not medical advice
- Keep language professional and EU-pharma appropriate

LANGUAGE — VERY IMPORTANT:
- Write the `answer`, every entry in `key_points`, and the `disclaimer` in {lang_name}.
- The `sentiment_summary` field MUST stay in English: exactly one of "Positive", "Mixed", "Negative", "Neutral".

GROUNDING — VERY IMPORTANT:
The user message contains a numbered list of source snippets like "[1] ...", "[2] ...".
- Every factual claim in `answer` and `key_points` that comes from a source MUST cite it inline using bracket markers, e.g. "Patients report mild nausea [2][5]."
- Use ONLY the numbers that appear in the provided sources list. Never invent citations.
- If a claim is general pharmacological knowledge and not from the sources, leave it uncited.
- If no sources are provided, omit citations entirely.

Respond ONLY with valid JSON in this exact structure:
{{
  "answer": "<main summary paragraph with [n] citations, in {lang_name}>",
  "key_points": ["<point with [n] citations, in {lang_name}>", "<point>", "<point>"],
  "sentiment_summary": "Positive|Mixed|Negative|Neutral",
  "disclaimer": "<one-sentence medical/regulatory disclaimer, in {lang_name}>"
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


class AISearchFromResultsRequest(BaseModel):
    """Bridge from Live Search → AI Mode. The frontend forwards already-fetched
    live results so we don't refetch news."""
    q: str
    sources: List[AISearchSource]
    lang: Optional[str] = "en"


def _simple_sentiment(text: str) -> str:
    tl = text.lower()
    neg_words = ["side effect", "adverse", "pain", "dangerous", "overdose", "rash",
                 "allergy", "worse", "terrible", "effet secondaire", "bijwerking"]
    pos_words = ["great", "excellent", "effective", "recommend", "relief", "better",
                 "good", "safe", "efficace", "excellent", "recommande"]
    neg_hits = sum(1 for w in neg_words if w in tl)
    pos_hits = sum(1 for w in pos_words if w in tl)
    if neg_hits > pos_hits:
        return "negative"
    if pos_hits > neg_hits:
        return "positive"
    return "neutral"


def _fetch_one_news_dict(query: str, lang: str, geo: str, ceid: str, per_query: int) -> List[dict]:
    """Single Google News RSS fetch returning dicts (the AI-side context shape)."""
    import feedparser
    from urllib.parse import quote_plus
    from email.utils import parsedate_to_datetime
    from bs4 import BeautifulSoup

    url = (
        f"https://news.google.com/rss/search"
        f"?q={quote_plus(query)}&hl={lang}&gl={geo}&ceid={ceid}"
    )
    out: List[dict] = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:per_query]:
            link = getattr(entry, "link", None) or getattr(entry, "id", None)
            if not link:
                continue
            title = getattr(entry, "title", "") or ""
            summary = getattr(entry, "summary", "") or ""
            clean = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)
            text = f"{title}. {clean}".strip() if clean else title.strip()
            if len(text) < 20:
                continue
            published_at = None
            if hasattr(entry, "published"):
                try:
                    published_at = parsedate_to_datetime(entry.published).isoformat()
                except Exception:
                    pass
            out.append({
                "source_type": "news",
                "source_url": link,
                "country": geo,
                "language": lang,
                "text": text[:400],
                "published_at": published_at,
                "sentiment": _simple_sentiment(text),
            })
    except Exception:
        return []
    return out


async def _fetch_news_context(queries: List[str], max_results: int = 8) -> List[dict]:
    """Quick Google News RSS fetch to provide grounding context for the LLM.

    Parallelised across (query × locale) combos so cross-lingual expansion doesn't
    blow past the 10s timeout on cold start.
    """
    import functools
    from concurrent.futures import ThreadPoolExecutor

    locales = [("en", "GB", "GB:en"), ("fr", "FR", "FR:fr")]
    per_query = max(2, max_results // max(1, len(queries)))

    def _sync_fetch():
        tasks = [(q, lang, geo, ceid) for q in queries for (lang, geo, ceid) in locales]
        if not tasks:
            return []
        results: List[dict] = []
        seen_urls: set = set()
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(_fetch_one_news_dict, q, lang, geo, ceid, per_query)
                for (q, lang, geo, ceid) in tasks
            ]
            for fut in futures:
                try:
                    for d in fut.result(timeout=8) or []:
                        u = d.get("source_url")
                        if not u or u in seen_urls:
                            continue
                        seen_urls.add(u)
                        results.append(d)
                        if len(results) >= max_results:
                            break
                except Exception:
                    continue
                if len(results) >= max_results:
                    break
        return results[:max_results]

    try:
        loop = asyncio.get_running_loop()
        fn = functools.partial(_sync_fetch)
        return await asyncio.wait_for(loop.run_in_executor(None, fn), timeout=14.0)
    except Exception:
        return []


def _raw_mention_to_dict(rm) -> dict:
    """Adapter: ingestion RawMention → AI grounding dict shape."""
    return {
        "source_type": rm.source_type,
        "source_url": rm.source_url,
        "country": rm.country,
        "language": rm.language,
        # Reference sources (Wikipedia, PubMed) are factual, not opinion — flag neutral.
        "sentiment": "neutral",
        "text": (rm.raw_text or "")[:400],
        "published_at": rm.published_at.isoformat() if rm.published_at else None,
    }


async def _fetch_wikipedia_grounding(queries: List[str]) -> List[dict]:
    try:
        from ingestion.connectors.wikipedia import WikipediaConnector
        rms = await asyncio.wait_for(
            WikipediaConnector().collect(
                queries, ["GB", "FR", "NL", "DE", "BE"], ["en", "fr", "nl", "de"]
            ),
            timeout=9.0,
        )
        return [_raw_mention_to_dict(rm) for rm in rms]
    except Exception:
        return []


async def _fetch_pubmed_grounding(queries: List[str]) -> List[dict]:
    try:
        from ingestion.connectors.pubmed import PubMedConnector
        rms = await asyncio.wait_for(
            PubMedConnector().collect(queries, ["GB"], ["en"]),
            timeout=10.0,
        )
        return [_raw_mention_to_dict(rm) for rm in rms]
    except Exception:
        return []


async def _fetch_clinical_trials_grounding(queries: List[str]) -> List[dict]:
    try:
        from ingestion.connectors.clinical_trials import ClinicalTrialsConnector
        rms = await asyncio.wait_for(
            ClinicalTrialsConnector().collect(queries, ["GB"], ["en"]),
            timeout=10.0,
        )
        return [_raw_mention_to_dict(rm) for rm in rms]
    except Exception:
        return []


async def _fetch_openfda_grounding(queries: List[str]) -> List[dict]:
    try:
        from ingestion.connectors.openfda import OpenFDAConnector
        rms = await asyncio.wait_for(
            OpenFDAConnector().collect(queries, ["GB"], ["en"]),
            timeout=12.0,
        )
        return [_raw_mention_to_dict(rm) for rm in rms]
    except Exception:
        return []


def _round_robin_dedupe(buckets: List[List[dict]], max_results: int) -> List[dict]:
    """Interleave per-source lists so the AI sees a mix, not 8 news in a row.

    Dedup by URL since the same article can surface across our fan-out locales.
    """
    out: List[dict] = []
    seen_urls: set = set()
    i = 0
    while len(out) < max_results and any(bucket for bucket in buckets):
        bucket = buckets[i % len(buckets)]
        i += 1
        if not bucket:
            continue
        item = bucket.pop(0)
        url = item.get("source_url")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        out.append(item)
    return out


async def _fetch_grounding_context(queries: List[str], max_results: int = 8) -> List[dict]:
    """Multi-source grounding: News + Wikipedia + PubMed in parallel.

    Each source is wrapped in its own timeout so a single slow upstream
    can't take down the whole fan-out. Results are round-robin merged so
    the LLM gets a balanced mix rather than 8 news articles in a row.
    """
    news, wiki, pubmed, trials, fda = await asyncio.gather(
        _fetch_news_context(queries, max_results=max_results),
        _fetch_wikipedia_grounding(queries),
        _fetch_pubmed_grounding(queries),
        _fetch_clinical_trials_grounding(queries),
        _fetch_openfda_grounding(queries),
        return_exceptions=True,
    )
    buckets = [r if isinstance(r, list) else [] for r in (news, wiki, pubmed, trials, fda)]
    return _round_robin_dedupe(buckets, max_results)


def _build_context_block(sources: List[dict]) -> str:
    """Format numbered context block — the [n] indices align with `sources`
    output order so the model's citations map to the source cards 1-to-1."""
    if not sources:
        return ""
    lines = []
    for i, r in enumerate(sources[:8], start=1):
        country = r.get("country", "") or ""
        snippet = (r.get("text") or "")[:220].replace("\n", " ").strip()
        lines.append(f"[{i}] ({r.get('source_type', 'src').upper()} · {country}) {snippet}")
    return "\n\nNumbered sources for grounding (cite using [n]):\n" + "\n".join(lines)


async def _synthesise(
    query: str,
    sources: List[dict],
    expanded_terms: List[str],
    t0: float,
    lang: str = "en",
) -> AISearchResponse:
    """Shared LLM call used by both GET and POST endpoints."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    lang = lang if lang in _LANG_NAMES else "en"

    expansion_note = ""
    if len(expanded_terms) > 1:
        expansion_note = (
            f"\n\nNote: '{query}' was expanded across EU brand variants: "
            f"{', '.join(expanded_terms)}."
        )

    user_message = (
        f'Analyse this pharmaceutical query: "{query}"'
        f"{expansion_note}"
        f"{_build_context_block(sources)}"
    )

    try:
        completion = await asyncio.wait_for(
            client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _build_system_prompt(lang)},
                    {"role": "user", "content": user_message},
                ],
                max_completion_tokens=700,
                response_format={"type": "json_object"},
            ),
            timeout=20.0,
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

    return AISearchResponse(
        query=query,
        answer=answer,
        key_points=key_points,
        sentiment_summary=sentiment_summary,
        disclaimer=disclaimer,
        sources=source_models,
        expanded_terms=expanded_terms,
        model=settings.OPENAI_MODEL,
        elapsed_ms=int((time.time() - t0) * 1000),
    )


@router.get("/ai", response_model=AISearchResponse)
async def ai_search(
    q: str = Query(..., min_length=2, description="Brand, drug, or topic to analyse"),
    lang: str = Query("en", description="Output language: en, fr, nl, de"),
    current_user: User = Depends(get_current_user),
):
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API key not configured. Set OPENAI_API_KEY in your .env file.",
        )

    t0 = time.time()
    expanded = expand_query(q.strip(), max_terms=5)
    live_results = await _fetch_grounding_context(expanded)
    return await _synthesise(q, live_results, expanded, t0, lang=lang)


@router.post("/ai", response_model=AISearchResponse)
async def ai_search_from_results(
    payload: AISearchFromResultsRequest,
    current_user: User = Depends(get_current_user),
):
    """Bridge endpoint: synthesise from results the user already saw in Live
    Search. Skips the fresh news fetch — the live snippets ARE the context."""
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API key not configured. Set OPENAI_API_KEY in your .env file.",
        )

    t0 = time.time()
    expanded = expand_query(payload.q.strip(), max_terms=5)
    sources = [s.model_dump() for s in payload.sources][:8]
    return await _synthesise(payload.q, sources, expanded, t0, lang=payload.lang or "en")
