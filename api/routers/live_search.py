"""
Live search — fires real connectors in parallel, enriches with NLP, returns immediately.
No DB read or write — pure real-time search against live sources.
"""
import asyncio
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel

from api.dependencies import get_current_user
from core.logging import get_logger
from core.role_lens import resolve_role, role_label, role_sort_key
from core.search_metrics import SearchIntelligence
from intelligence.search_intelligence import build_search_intelligence, flatten_for_db
from core.search_audit import log_search_query
from models.search_audit import SearchMode
from models.user import User

logger = get_logger(__name__)


def _enqueue_corpus_ingest(payload: list) -> None:
    """Governed async enrichment: hand live-search results to the connector
    ingest pipeline (DPIA-gated, dedup, classification downstream). Best-effort —
    a missing/unavailable Celery broker must never affect the search response."""
    from core.config import settings
    if not settings.DPIA_PROCESSING_ENABLED or not payload:
        return
    try:
        from ingestion.tasks import ingest_live_results
        ingest_live_results.delay(payload)
    except Exception as exc:  # broker down, serialization, etc.
        logger.warning("live_ingest_enqueue_failed", error=str(exc))

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
    # Source-specific extras (e.g. YouTube views/likes/comments/channel/thumbnail).
    # Generic dict so a new connector can attach its own fields without a schema bump.
    meta: Optional[dict] = None


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
    role: str
    role_label: str
    metrics: SearchIntelligence


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


# YouTube search.list costs 100 quota units/call (default 10k/day). Cross-lingual
# expansion (up to 8 terms) × multiple countries would burn the whole day's quota
# in a handful of searches, so we cap what YouTube sees and cache results.
_YT_MAX_KEYWORDS = 2
_YT_MAX_COUNTRIES = 1
_YT_CACHE_TTL = 1800.0  # 30 min — repeat demo queries don't re-hit the API
_yt_cache: dict[tuple, tuple[float, list]] = {}


async def _run_youtube(keywords: List[str], countries: List[str], languages: List[str]):
    from ingestion.connectors.youtube import YouTubeConnector, YouTubeQuotaError

    c = YouTubeConnector()
    if not c.is_available():
        return []

    # Quota frugality: only the primary term(s) + first country reach the API.
    kws = keywords[: _YT_MAX_KEYWORDS]
    cs = countries[: _YT_MAX_COUNTRIES] or ["FR"]

    cache_key = (tuple(kws), tuple(cs))
    hit = _yt_cache.get(cache_key)
    if hit and (time.time() - hit[0]) < _YT_CACHE_TTL:
        return hit[1]

    try:
        res = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                lambda: asyncio.run(c.collect(kws, cs, languages)),
            ),
            timeout=12.0,
        )
    except YouTubeQuotaError:
        # Let it propagate → surfaces as an explicit "error" source-notice.
        raise
    except (asyncio.TimeoutError, Exception) as exc:
        # Quota errors can also bubble up wrapped; re-raise those, swallow the rest.
        if "quota" in str(exc).lower() or "ratelimitexceeded" in str(exc).lower():
            raise YouTubeQuotaError(
                "YouTube Data API daily quota exhausted — resets ~09:00 CET (midnight US-Pacific)."
            )
        return []

    _yt_cache[cache_key] = (time.time(), res)
    return res


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


async def _run_eudravigilance(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        from ingestion.connectors.eudravigilance import EudraVigilanceConnector
        return await asyncio.wait_for(
            EudraVigilanceConnector().collect(keywords, countries, languages),
            timeout=14.0,
        )
    except Exception:
        return []


async def _run_doctissimo(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        from ingestion.connectors.doctissimo import DoctissimoConnector
        c = DoctissimoConnector()
        if not c.is_available():
            return []
        return await asyncio.wait_for(
            c.collect(keywords, countries, languages),
            timeout=20.0,
        )
    except Exception:
        return []


async def _run_belgium_health(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        from ingestion.connectors.belgium_health_data import BelgiumHealthDataConnector
        return await asyncio.wait_for(
            BelgiumHealthDataConnector().collect(keywords, countries, languages),
            timeout=15.0,
        )
    except Exception:
        return []


async def _run_ansm(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        from ingestion.connectors.ansm import ANSMConnector
        return await asyncio.wait_for(
            ANSMConnector().collect(keywords, countries, languages),
            timeout=15.0,
        )
    except Exception:
        return []


async def _run_belgium_hcp(keywords: List[str], countries: List[str], languages: List[str]):
    try:
        from ingestion.connectors.belgium_hcp import BelgiumHCPConnector
        return await asyncio.wait_for(
            BelgiumHCPConnector().collect(keywords, countries, languages),
            timeout=18.0,
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


_PERIOD_DAYS = {"7d": 7, "30d": 30, "180d": 180, "365d": 365}


_LOCALE_MAP = [
    ("fr", "BE", "BE:fr"),
    ("nl", "BE", "BE:nl"),
    ("de", "BE", "BE:de"),
    ("fr", "FR", "FR:fr"),
    ("en", "BE", "BE:en"),
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
    "wikipedia": _run_wikipedia,
    "pubmed": _run_pubmed,
    "youtube": _run_youtube,
    "clinical_trials": _run_clinical_trials,
    "openfda": _run_openfda,
    "eudravigilance": _run_eudravigilance,
    "app_store": _run_app_store,
    "doctissimo": _run_doctissimo,
    "belgium_health": _run_belgium_health,
    "belgium_hcp": _run_belgium_hcp,
    "ansm": _run_ansm,
}

# Belgium-first default: EU pharmacovigilance + Belgian health-data (FAGG/AFMPS
# shortages) + French ANSM shortages/safety + the multilingual baseline.
# openFDA stays available opt-in via ?sources=openfda.
DEFAULT_SOURCES = [
    "news", "rss", "wikipedia", "pubmed", "youtube",
    "eudravigilance", "belgium_health", "ansm",
]


# Sources that need a key to function. The endpoint surfaces this in
# `source_notices` so the UI can tell the user *why* a source is empty.
def _missing_key_reason(source: str) -> Optional[str]:
    from core.config import settings
    if source == "youtube" and not settings.YOUTUBE_API_KEY:
        return "YOUTUBE_API_KEY is not configured in .env"
    return None


# ── endpoint ──────────────────────────────────────────────────────────────────
@router.get("/live", response_model=LiveSearchResponse)
async def live_search(
    background_tasks: BackgroundTasks,
    q: str = Query(..., min_length=2, description="Brand, drug, or keyword to search live"),
    sources: Optional[str] = Query(None, description="Comma-separated: news,rss,forum,wikipedia,pubmed,youtube,clinical_trials,openfda,app_store,safety_gate"),
    languages: Optional[str] = Query("fr,nl,de,en", description="Comma-separated language codes (BE: fr,nl,de + FR: fr; en for fallback)"),
    period: str = Query("all", description="Time window: 7d, 30d, 180d, 365d, all"),
    role: Optional[str] = Query(None, description="Role lens: pharmacist, marketing, brand_manager, admin (admins may view-as any; others locked to own role)"),
    current_user: User = Depends(get_current_user),
):
    import time
    from datetime import date, timedelta, timezone
    from processing.query_expansion import expand_query
    t0 = time.time()

    lens = resolve_role(current_user, role)

    # max_terms=8 so a brand query surfaces its full EU variant set (e.g.
    # paracetamol → Doliprane, Dafalgan, Efferalgan, Panadol, Perdolan, ben-u-ron),
    # not just the canonical INN + translations. Trade-off: more keywords means a
    # wider news fan-out (keywords × locales), so latency rises modestly — tune
    # here if live search gets too slow on the default source set.
    kw_list = expand_query(q.strip(), max_terms=8)
    # Product market is Belgium (bilingual FR/NL; EN kept for international sources).
    lang_list = [l.strip() for l in (languages or "fr,nl,en").split(",") if l.strip()]
    source_list = [s.strip() for s in (sources or ",".join(DEFAULT_SOURCES)).split(",") if s.strip()]
    country_list = ["BE"]

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
            meta=(rm.metadata or None),
        ))

    if since_dt is not None:
        results = [r for r in results if r.published_at is None or r.published_at >= since_dt]

    # Role-aware ordering via deterministic priority TIERS (no score, no
    # engagement). Risk flags always stay on top (patient safety first for every
    # persona); then the role's source tier, then its topic tier, then freshness.
    # A pharmacist surfaces official safety/supply sources while marketing surfaces
    # reach/buzz — and because engagement no longer enters the sort, the role lens
    # is actually visible instead of being swamped by view counts.
    results.sort(
        key=lambda r: role_sort_key(lens, r.source_type, r.topic, r.is_risk, r.published_at),
    )

    # Build per-source notices so the UI can explain zero-result sources.
    # Count rows in `results` (post-dedupe, post-period-filter) per source.
    final_per_source: dict[str, int] = {s: 0 for s in runner_source_order}
    for r in results:
        if r.source_type in final_per_source:
            final_per_source[r.source_type] += 1

    notices: List[SourceNotice] = []
    for s in runner_source_order:
        if s in per_source_errors:
            err = per_source_errors[s]
            detail = err[:200] if "quota" in err.lower() else f"upstream error: {err[:200]}"
            notices.append(SourceNotice(
                source=s, status="error", count=0, detail=detail,
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

    elapsed_ms = int((time.time() - t0) * 1000)

    # Per-search DIA intelligence (snapshot + framework for the resolved brand),
    # computed off-thread because the framework modules use a sync DB session.
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
                "engagement": r.engagement,
            }
            for r in results
        ],
        lens, q, kw_list, "live",
    )

    background_tasks.add_task(
        log_search_query,
        mode=SearchMode.live,
        q=q,
        user_id=current_user.id,
        lang=None,
        role=lens,
        sources_requested=source_list,
        expanded_terms=kw_list,
        filters={"period": period, "languages": lang_list, "countries": country_list},
        metrics=flatten_for_db(si),
        results=[
            {
                "rank": i,
                "source_type": r.source_type,
                "source_url": r.source_url,
                "snippet": r.text,
                "sentiment": r.sentiment,
                "topic": r.topic,
                "risk_type": r.risk_type,
                "country": r.country,
                "language": r.language,
                "published_at": r.published_at,
            }
            for i, r in enumerate(results, start=1)
        ],
        elapsed_ms=elapsed_ms,
    )

    # Governed async corpus enrichment — route the same results through the
    # connector ingest pipeline so they become classified `mentions` over time.
    background_tasks.add_task(
        _enqueue_corpus_ingest,
        [
            {
                "source_type": r.source_type,
                "source_url": r.source_url,
                "country": r.country,
                "language": r.language,
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "raw_text": r.text,
                "query_used": r.query or q,
                "engagement_count": r.engagement,
                "metadata": r.meta or {},
            }
            for r in results
        ],
    )

    return LiveSearchResponse(
        query=q,
        total=len(results),
        results=results,
        sources_queried=source_list,
        source_notices=notices,
        expanded_terms=kw_list,
        elapsed_ms=elapsed_ms,
        role=lens,
        role_label=role_label(lens),
        metrics=si,
    )
