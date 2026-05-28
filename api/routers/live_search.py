"""
Live search — fires real connectors in parallel, enriches with NLP, returns immediately.
No DB read or write — pure real-time search against live sources.
"""
import asyncio
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.dependencies import get_current_user
from models.user import User

router = APIRouter()

# ── lightweight rule-based sentiment (no ML model load latency) ──────────────
_POS = {
    "en": ["great", "excellent", "helped", "works", "effective", "recommend", "relief",
           "better", "good", "perfect", "love", "amazing", "best", "safe"],
    "fr": ["excellent", "efficace", "bien", "soulagé", "recommande", "parfait",
           "super", "bon", "aide", "meilleur", "formidable"],
    "nl": ["uitstekend", "helpt", "goed", "effectief", "aanraden", "prima",
           "werkt", "beste", "fijn"],
    "de": ["ausgezeichnet", "hilft", "gut", "wirksam", "empfehlen", "prima",
           "wirkt", "beste", "toll"],
}
_NEG = {
    "en": ["side effect", "adverse", "pain", "dizzy", "nausea", "vomit", "hospital",
           "dangerous", "overdose", "rash", "allergy", "worse", "bad", "terrible",
           "horrible", "awful", "hurts", "bleeding", "faint", "seizure"],
    "fr": ["effet secondaire", "douleur", "vertige", "nausée", "vomissement",
           "dangereux", "surdosage", "éruption", "allergie", "pire", "mauvais",
           "hospitalisé", "urgence"],
    "nl": ["bijwerking", "pijn", "duizelig", "misselijk", "overgeven", "ziekenhuis",
           "gevaarlijk", "overdosering", "uitslag", "allergie", "erger"],
    "de": ["nebenwirkung", "schmerz", "schwindel", "übelkeit", "erbrechen",
           "krankenhaus", "gefährlich", "überdosierung", "ausschlag", "allergie"],
}


def _simple_sentiment(text: str, lang: str) -> str:
    tl = text.lower()
    neg_words = _NEG.get(lang, _NEG["en"]) + _NEG["en"]
    pos_words = _POS.get(lang, _POS["en"]) + _POS["en"]
    neg_hits = sum(1 for w in neg_words if w in tl)
    pos_hits = sum(1 for w in pos_words if w in tl)
    if neg_hits > pos_hits:
        return "negative"
    if pos_hits > neg_hits:
        return "positive"
    return "neutral"


def _simple_topic(text: str) -> str:
    tl = text.lower()
    if any(w in tl for w in ["side effect", "adverse", "reaction", "effet secondaire",
                               "bijwerking", "nebenwirkung", "nausea", "pain", "douleur",
                               "vertige", "pijn", "schmerz", "rash", "allergi"]):
        return "side_effect"
    if any(w in tl for w in ["price", "cost", "cheap", "expensive", "prix", "coût",
                               "prijs", "goedkoop", "preis"]):
        return "price"
    if any(w in tl for w in ["work", "effect", "relief", "helps", "efficac", "works",
                               "wirkt", "werkt", "fonctionne", "aide"]):
        return "efficacy"
    if any(w in tl for w in ["stock", "available", "find", "shortage", "rupture",
                               "uitverkocht", "ausverkauft"]):
        return "availability"
    if any(w in tl for w in ["recommend", "suggest", "try", "recommande", "aanraden",
                               "empfehlen"]):
        return "recommendation"
    return "general"


# ── response schema ───────────────────────────────────────────────────────────
class LiveSearchResult(BaseModel):
    source_type: str
    source_url: Optional[str]
    country: Optional[str]
    language: Optional[str]
    published_at: Optional[datetime]
    text: str
    sentiment: str
    topic: str
    risk_type: str
    is_risk: bool
    engagement: Optional[int]
    query: str


class SourceNotice(BaseModel):
    source: str
    status: str  # "ok" | "missing_key" | "empty" | "error"
    count: int
    detail: Optional[str] = None


class LiveSearchResponse(BaseModel):
    query: str
    total: int
    results: List[LiveSearchResult]
    sources_queried: List[str]
    source_notices: List[SourceNotice]
    expanded_terms: List[str]
    elapsed_ms: int


# ── connector runners — all blocking I/O in threads to keep event loop free ──
def _rss_sync(keywords: List[str], countries: List[str], languages: List[str]):
    """Sync wrapper for RSSNewsConnector — runs in thread pool."""
    import asyncio as _aio
    try:
        from ingestion.connectors.rss_news import RSSNewsConnector
        return _aio.run(RSSNewsConnector().collect(keywords, countries, languages))
    except Exception:
        return []


async def _run_rss(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, _rss_sync, keywords, countries, languages),
            timeout=8.0,
        )
    except Exception:
        return []


async def _run_forum(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        from ingestion.connectors.forum_scraper import ForumScraperConnector
        return await asyncio.wait_for(
            ForumScraperConnector().collect(keywords, countries, languages),
            timeout=5.0,
        )
    except Exception:
        return []


async def _run_google_trends(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        from ingestion.connectors.google_trends import GoogleTrendsConnector
        c = GoogleTrendsConnector()
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: asyncio.run(c.collect(keywords, countries, languages)),
            ),
            timeout=8.0,
        )
    except Exception:
        return []


async def _run_reddit(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        from ingestion.connectors.reddit import RedditConnector
        c = RedditConnector()
        if not c.is_available():
            return []
        return await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                lambda: asyncio.run(c.collect(keywords, countries, languages)),
            ),
            timeout=15.0,
        )
    except Exception:
        return []


async def _run_wikipedia(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        from ingestion.connectors.wikipedia import WikipediaConnector
        return await asyncio.wait_for(
            WikipediaConnector().collect(keywords, countries, languages),
            timeout=10.0,
        )
    except Exception:
        return []


async def _run_pubmed(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        from ingestion.connectors.pubmed import PubMedConnector
        return await asyncio.wait_for(
            PubMedConnector().collect(keywords, countries, languages),
            timeout=12.0,
        )
    except Exception:
        return []


async def _run_youtube(keywords: List[str], countries: List[str], languages: List[str]):
    # YouTube connector blocks on googleapiclient internally — wrap in executor
    # the same way the reddit runner does so the event loop stays free.
    try:
        from ingestion.connectors.youtube import YouTubeConnector
        c = YouTubeConnector()
        if not c.is_available():
            return []
        return await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                lambda: asyncio.run(c.collect(keywords, countries, languages)),
            ),
            timeout=12.0,
        )
    except Exception:
        return []


async def _run_clinical_trials(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        from ingestion.connectors.clinical_trials import ClinicalTrialsConnector
        return await asyncio.wait_for(
            ClinicalTrialsConnector().collect(keywords, countries, languages),
            timeout=12.0,
        )
    except Exception:
        return []


async def _run_openfda(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        from ingestion.connectors.openfda import OpenFDAConnector
        return await asyncio.wait_for(
            OpenFDAConnector().collect(keywords, countries, languages),
            timeout=14.0,
        )
    except Exception:
        return []


async def _run_app_store(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        from ingestion.connectors.app_store import AppStoreReviewsConnector
        return await asyncio.wait_for(
            AppStoreReviewsConnector().collect(keywords, countries, languages),
            timeout=10.0,
        )
    except Exception:
        return []


async def _run_trustpilot(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        from ingestion.connectors.trustpilot import TrustpilotConnector
        c = TrustpilotConnector()
        if not c.is_available():
            return []
        return await asyncio.wait_for(
            c.collect(keywords, countries, languages),
            timeout=12.0,
        )
    except Exception:
        return []


_PERIOD_DAYS = {"7d": 7, "30d": 30, "180d": 180, "365d": 365}


_LOCALE_MAP = [
    ("en", "GB", "GB:en"),
    ("fr", "FR", "FR:fr"),
    ("nl", "NL", "NL:nl"),
    ("de", "DE", "DE:de"),
    ("fr", "BE", "BE:fr"),
]


def _fetch_one_news_feed(keyword: str, lang: str, geo: str, ceid: str, since_date: Optional[str]):
    """Single Google News RSS fetch. Returns a list of RawMention (possibly empty)."""
    import feedparser
    from urllib.parse import quote_plus
    from email.utils import parsedate_to_datetime
    from bs4 import BeautifulSoup
    from ingestion.connectors.base import RawMention

    kw_q = f"{keyword} after:{since_date}" if since_date else keyword
    url = (
        f"https://news.google.com/rss/search"
        f"?q={quote_plus(kw_q)}"
        f"&hl={lang}&gl={geo}&ceid={ceid}"
    )
    out = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:12]:
            link = getattr(entry, "link", None) or getattr(entry, "id", None)
            if not link:
                continue
            title = getattr(entry, "title", "") or ""
            summary = getattr(entry, "summary", "") or ""
            clean_summary = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)
            title_stub = title.lower()[:60]
            if clean_summary and not clean_summary.lower().startswith(title_stub):
                text = f"{title}. {clean_summary}".strip().rstrip(".")
            else:
                text = title.strip()
            if len(text) < 20:
                continue
            published_at = None
            if hasattr(entry, "published"):
                try:
                    published_at = parsedate_to_datetime(entry.published)
                except Exception:
                    pass
            out.append(RawMention(
                source_type="news",
                source_url=link,
                country=geo,
                language=lang,
                published_at=published_at,
                raw_text=text,
                query_used=keyword,
            ))
    except Exception:
        return []
    return out


def _web_news_sync(
    keywords: List[str],
    countries: List[str],
    languages: List[str],
    since_date: Optional[str] = None,
):
    """Parallelised Google News RSS fetch.

    Cross-lingual query expansion can produce up to 4 keywords × 5 locales = 20 fetches.
    Doing those sequentially blew past the 12s outer timeout on cold start (DNS / TLS
    warm-up), which made first-time searches return zero results. Running them through
    a ThreadPoolExecutor pulls the wall-clock down to ~3s for the same fan-out.
    """
    from concurrent.futures import ThreadPoolExecutor

    tasks = []
    for keyword in keywords:
        for lang, geo, ceid in _LOCALE_MAP:
            if lang not in languages and geo not in countries:
                continue
            tasks.append((keyword, lang, geo, ceid))

    if not tasks:
        return []

    results = []
    seen_urls: set = set()
    # 8 workers handles the 20-task worst case in ~3 batches without overwhelming google news.
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(_fetch_one_news_feed, kw, lang, geo, ceid, since_date)
            for (kw, lang, geo, ceid) in tasks
        ]
        for fut in futures:
            try:
                for rm in fut.result(timeout=10) or []:
                    if rm.source_url in seen_urls:
                        continue
                    seen_urls.add(rm.source_url)
                    results.append(rm)
            except Exception:
                continue
    return results


async def _run_web_news(
    keywords: List[str],
    countries: List[str],
    languages: List[str],
    since_date: Optional[str] = None,
):
    """Google News RSS — runs sync fetcher in thread to keep event loop free."""
    import functools
    try:
        loop = asyncio.get_running_loop()
        fn = functools.partial(_web_news_sync, keywords, countries, languages, since_date)
        return await asyncio.wait_for(
            loop.run_in_executor(None, fn),
            timeout=18.0,
        )
    except Exception:
        return []


_SOURCE_RUNNERS = {
    "news": _run_web_news,
    "rss": _run_rss,
    "forum": _run_forum,
    "google_trends": _run_google_trends,
    "reddit": _run_reddit,
    "wikipedia": _run_wikipedia,
    "pubmed": _run_pubmed,
    "youtube": _run_youtube,
    "clinical_trials": _run_clinical_trials,
    "openfda": _run_openfda,
    "app_store": _run_app_store,
    "trustpilot": _run_trustpilot,
}

DEFAULT_SOURCES = ["news", "rss", "wikipedia", "pubmed"]


# Sources that need a key to function. The endpoint surfaces this in
# `source_notices` so the UI can tell the user *why* a source is empty.
def _missing_key_reason(source: str) -> Optional[str]:
    from core.config import settings
    if source == "youtube" and not settings.YOUTUBE_API_KEY:
        return "YOUTUBE_API_KEY is not configured in .env"
    if source == "reddit" and not (settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET):
        return "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are not configured in .env"
    if source == "trustpilot" and not settings.TRUSTPILOT_API_KEY:
        return "TRUSTPILOT_API_KEY is not configured in .env"
    return None


# ── endpoint ──────────────────────────────────────────────────────────────────
@router.get("/live", response_model=LiveSearchResponse)
async def live_search(
    q: str = Query(..., min_length=2, description="Brand, drug, or keyword to search live"),
    sources: Optional[str] = Query(None, description="Comma-separated: news,rss,forum,google_trends,reddit,wikipedia,pubmed,youtube,clinical_trials,openfda,app_store,trustpilot"),
    languages: Optional[str] = Query("fr,nl,en,de", description="Comma-separated language codes"),
    period: str = Query("all", description="Time window: 7d, 30d, 180d, 365d, all"),
    current_user: User = Depends(get_current_user),
):
    import time
    from datetime import date, timedelta, timezone
    from processing.query_expansion import expand_query
    t0 = time.time()

    kw_list = expand_query(q.strip(), max_terms=4)
    lang_list = [l.strip() for l in (languages or "fr,nl,en,de").split(",") if l.strip()]
    source_list = [s.strip() for s in (sources or ",".join(DEFAULT_SOURCES)).split(",") if s.strip()]
    country_list = ["GB", "FR", "NL", "DE", "BE"]

    since_dt = None
    since_date_str = None
    if period in _PERIOD_DAYS:
        delta = timedelta(days=_PERIOD_DAYS[period])
        since_dt = datetime.now(timezone.utc) - delta
        since_date_str = (date.today() - delta).isoformat()

    # Track which source each runner result came from so we can emit
    # per-source diagnostics in `source_notices`.
    runners = []
    runner_source_order: List[str] = []
    for s in source_list:
        if s not in _SOURCE_RUNNERS:
            continue
        runner_source_order.append(s)
        if s == "news":
            runners.append(_run_web_news(kw_list, country_list, lang_list, since_date_str))
        else:
            runners.append(_SOURCE_RUNNERS[s](kw_list, country_list, lang_list))

    raw_lists = await asyncio.gather(*runners, return_exceptions=True)

    # Per-source row counts BEFORE any filtering — used for the notices below.
    per_source_raw_counts: dict[str, int] = {s: 0 for s in runner_source_order}
    per_source_errors: dict[str, Optional[str]] = {}
    for s, r in zip(runner_source_order, raw_lists):
        if isinstance(r, list):
            per_source_raw_counts[s] = len(r)
        else:
            per_source_errors[s] = str(r) if r else "unknown error"

    from processing.language_detection import detect_language
    from processing.risk_detector import detect_risk

    raw_mentions = []
    for r in raw_lists:
        if isinstance(r, list):
            raw_mentions.extend(r)

    results: List[LiveSearchResult] = []
    seen_texts: set = set()

    for rm in raw_mentions:
        text = (rm.raw_text or "").strip()
        if not text or len(text) < 20:
            continue
        key = text[:120]
        if key in seen_texts:
            continue
        seen_texts.add(key)

        lang = rm.language or detect_language(text) or "en"
        risk = detect_risk(text, lang)
        sentiment = _simple_sentiment(text, lang)
        topic = _simple_topic(text)

        if risk.risk_type != "none":
            sentiment = "negative"

        results.append(LiveSearchResult(
            source_type=rm.source_type,
            source_url=rm.source_url,
            country=rm.country,
            language=lang,
            published_at=rm.published_at,
            text=text[:800],
            sentiment=sentiment,
            topic=topic,
            risk_type=risk.risk_type,
            is_risk=risk.risk_type != "none",
            engagement=rm.engagement_count,
            query=rm.query_used,
        ))

    if since_dt is not None:
        results = [r for r in results if r.published_at is None or r.published_at >= since_dt]

    results.sort(key=lambda r: (r.is_risk, r.engagement or 0), reverse=True)

    # Build per-source notices so the UI can explain zero-result sources.
    # Count rows in `results` (post-dedupe, post-period-filter) per source.
    final_per_source: dict[str, int] = {s: 0 for s in runner_source_order}
    for r in results:
        if r.source_type in final_per_source:
            final_per_source[r.source_type] += 1

    notices: List[SourceNotice] = []
    for s in runner_source_order:
        if s in per_source_errors:
            notices.append(SourceNotice(
                source=s, status="error", count=0,
                detail=f"upstream error: {per_source_errors[s][:200]}",
            ))
            continue
        count_final = final_per_source[s]
        if count_final > 0:
            notices.append(SourceNotice(source=s, status="ok", count=count_final))
            continue
        # 0 final rows — explain why
        missing = _missing_key_reason(s)
        if missing:
            notices.append(SourceNotice(
                source=s, status="missing_key", count=0, detail=missing,
            ))
        else:
            raw = per_source_raw_counts.get(s, 0)
            notices.append(SourceNotice(
                source=s, status="empty", count=0,
                detail=(
                    f"no matches for this keyword in {s}" if raw == 0
                    else f"{raw} candidates were dropped by dedupe / period filter"
                ),
            ))

    return LiveSearchResponse(
        query=q,
        total=len(results),
        results=results,
        sources_queried=source_list,
        source_notices=notices,
        expanded_terms=kw_list,
        elapsed_ms=int((time.time() - t0) * 1000),
    )
