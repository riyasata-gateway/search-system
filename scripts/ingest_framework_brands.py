"""Fetch real multi-source data for every framework brand and link it.

The connectors in `ingestion/connectors/` are functional but were never run for
the tracked brands (scheduled ingestion is DPIA-gated off, and most sources only
fire on a live search), so the framework brands had only their imported reviews.
Data is the product — this pulls the **free, no-API-key** sources that the
environment can reach and that add genuine per-role signal:

  • PubMed            — evidence base / scientific interest      (source_type=pubmed)
  • ClinicalTrials.gov— pipeline / active trials                 (source_type=clinical_trials)
  • openFDA           — adverse-event & label safety signals     (source_type=openfda)
  • Google News RSS   — launches, recalls, PR / demand news      (source_type=rss/news)

Because we query *per brand*, we link each persisted mention straight to that
brand (MentionEntity) — no NLP entity-resolution needed. Deterministic, bounded
(cap per brand×source), idempotent (text_hash dedup), resilient (per-task
try/except + incremental commit).

Usage:  .venv/bin/python scripts/ingest_framework_brands.py [--limit N] [--sources pubmed,clinical_trials,openfda,rss]
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from core.config import settings
from core.framework_catalog import BRAND_INN
from intelligence.inn_resolver import resolve_inn
from ingestion.connectors.ansm import ANSMConnector
from ingestion.connectors.app_store import AppStoreReviewsConnector
from ingestion.connectors.bcfi import BCFIConnector
from ingestion.connectors.carenity import CarenityConnector
from ingestion.connectors.belgium_health_data import BelgiumHealthDataConnector
from ingestion.connectors.clinical_trials import ClinicalTrialsConnector
from ingestion.connectors.doctissimo import DoctissimoConnector
from ingestion.connectors.eudravigilance import EudraVigilanceConnector
from ingestion.connectors.forum_scraper import ForumScraperConnector
from ingestion.connectors.google_trends import GoogleTrendsConnector
from ingestion.connectors.openfda import OpenFDAConnector
from ingestion.connectors.pubmed import PubMedConnector
from ingestion.connectors.reddit import RedditConnector
from ingestion.connectors.rss_news import RSSNewsConnector
from ingestion.connectors.safety_gate import SafetyGateConnector
from ingestion.connectors.trustpilot import TrustpilotConnector
from ingestion.connectors.wikipedia import WikipediaConnector
from ingestion.connectors.youtube import YouTubeConnector
from ingestion.deduplication import compute_text_hash, is_text_too_short, sanitise_text
from models.brand import Brand
from models.mention import EntityType, Mention, MentionEntity
from processing.brand_match import text_mentions_brand, has_health_context, is_namesake_gated

CONTEXT_GATED_SOURCES = {"rss", "news", "youtube", "forum", "doctissimo", "reddit", "wikipedia"}

# Product market is Belgium. Belgium is bilingual (FR + NL), and we keep EN for
# international evidence sources (PubMed/trials). Country focus is strictly BE.
COUNTRIES = ["BE"]
LANGUAGES = ["fr", "nl", "en"]

# Substance-indexed sources: pharmacovigilance / drug DBs keyed by molecule (INN),
# not trade name. Skip brands that aren't medicines (no INN → no signal).
SUBSTANCE_SOURCES = {"openfda", "eudravigilance"}
# Scientific / clinical sources: keyed by the *molecule* for drugs (e.g.
# "levetiracetam", not "Keppra"), and by the brand for cosmetics. The ANSM (FR)
# and FAGG/Belgium shortage lists are indexed by molecule too, so they join here.
SCIENTIFIC_SOURCES = {"pubmed", "clinical_trials", "bcfi", "ansm", "belgium_health"}

# A molecule-queried paper relevant to more than this many tracked brands is a
# general/substance article, not brand-specific signal — don't attribute it.
MAX_EVIDENCE_FANOUT = 3


def _brand_terms(name: str):
    """Searchable trade-name term(s): split composite labels so
    'UCB brands (Keppra, Bimzelx)' → ['Keppra', 'Bimzelx'], 'Dafalgan' → ['Dafalgan']."""
    if "(" in name and ")" in name:
        inside = name[name.find("(") + 1:name.rfind(")")]
        parts = [p.strip() for p in inside.split(",") if p.strip()]
        if parts:
            return parts
    if "/" in name:
        return [p.strip() for p in name.split("/") if p.strip()]
    return [name]

CONNECTORS = {
    "pubmed": PubMedConnector,
    "clinical_trials": ClinicalTrialsConnector,
    "openfda": OpenFDAConnector,
    "rss": RSSNewsConnector,
    "forum": ForumScraperConnector,
    "youtube": YouTubeConnector,
    "wikipedia": WikipediaConnector,
    "app_store": AppStoreReviewsConnector,
    "eudravigilance": EudraVigilanceConnector,
    "bcfi": BCFIConnector,
    "google_trends": GoogleTrendsConnector,
    "reddit": RedditConnector,
    "ansm": ANSMConnector,
    "doctissimo": DoctissimoConnector,
    "carenity": CarenityConnector,
    "trustpilot": TrustpilotConnector,
    "safety_gate": SafetyGateConnector,
    # Belgium-native: FAGG/AFMPS shortages + BCFI/CBIP guidance + data.gov.be.
    "belgium_health": BelgiumHealthDataConnector,
}


# Per-source fetch timeout — a single hanging feed (e.g. a slow RSS endpoint with
# no socket timeout) must not stall the whole run. On timeout we skip that
# brand×source and move on.
_FETCH_TIMEOUT_S = 45


async def _collect(conn, keywords):
    return await asyncio.wait_for(
        conn.collect(keywords, COUNTRIES, LANGUAGES), timeout=_FETCH_TIMEOUT_S
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100, help="max mentions kept per brand × source (was 30 — raised so high-coverage brands aren't truncated)")
    ap.add_argument("--sources", default="pubmed,clinical_trials,openfda,rss")
    ap.add_argument("--only", default=None, help="comma-separated brand names to limit to (testing)")
    ap.add_argument("--all-brands", action="store_true",
                    help="ingest for EVERY catalogue brand (default: only the 31 workbook brands)")
    ap.add_argument("--no-data-only", action="store_true",
                    help="restrict to brands that currently have NO linked mentions (the 'grey' "
                         "brands) — implies --all-brands so the full catalogue is in scope")
    args = ap.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip() in CONNECTORS]
    conns = {s: CONNECTORS[s]() for s in sources}

    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        q = select(Brand).order_by(Brand.name)
        if not (args.all_brands or args.no_data_only):
            # Default stays framework-only; --all-brands opens it to the full
            # supplier catalogue (idempotent + resumable, so safe to re-run).
            q = q.where(Brand.category.isnot(None))
        brands = db.execute(q).scalars().all()
        if args.only:
            wanted = {n.strip().lower() for n in args.only.split(",")}
            brands = [b for b in brands if b.name.lower() in wanted]

        # Existing (brand_id) links so we stay idempotent on re-runs.
        linked = set(db.execute(
            select(MentionEntity.entity_id, MentionEntity.mention_id)
            .where(MentionEntity.entity_type == EntityType.brand)
        ).all())

        if args.no_data_only:
            # Only the "grey" brands — those with no linked mention at all.
            have = {bid for (bid, _mid) in linked}
            before = len(brands)
            brands = [b for b in brands if b.id not in have]
            print(f"--no-data-only: {len(brands)} of {before} brands have no linked data")

        totals = {s: 0 for s in sources}
        inn_cache: dict[str, list] = {}  # brand -> resolved substances (per run)
        for bi, brand in enumerate(brands, 1):
            print(f"\n[{bi}/{len(brands)}] {brand.name}")
            for s in sources:
                # Substance-indexed sources query by the brand's molecule (INN);
                # non-medicines have no INN, so there's no signal to fetch.
                inn = inn_cache.get(brand.name)
                if inn is None:
                    inn = resolve_inn(brand.name, BRAND_INN.get(brand.name)) or []
                    inn_cache[brand.name] = inn
                if s in SUBSTANCE_SOURCES:
                    # Pharmacovigilance is substance-only; non-medicines have none.
                    if not inn:
                        print(f"    {s:16s} — (not a medicine / no INN)")
                        continue
                    keywords = inn
                elif s in SCIENTIFIC_SOURCES:
                    # Evidence/pipeline: molecule for drugs, trade name for cosmetics.
                    keywords = inn or _brand_terms(brand.name)
                else:
                    # Public/conversation sources: search by real trade name(s).
                    keywords = _brand_terms(brand.name)
                try:
                    raws = asyncio.run(_collect(conns[s], keywords))
                except Exception as e:
                    print(f"    {s:16s} ERROR {type(e).__name__}: {str(e)[:80]}")
                    continue

                kept = 0
                for raw in raws:
                    if kept >= args.limit:
                        break
                    if is_text_too_short(raw.raw_text):
                        continue
                    th = compute_text_hash(raw)
                    existing = db.execute(
                        select(Mention).where(Mention.text_hash == th)
                    ).scalar_one_or_none()
                    if existing is not None:
                        m = existing
                        # Merge any new structured-metadata keys onto existing rows
                        # (backfills columns/fields added after first ingest).
                        if raw.metadata:
                            merged = {**(m.raw_metadata or {}), **raw.metadata}
                            if merged != (m.raw_metadata or {}):
                                m.raw_metadata = merged
                    else:
                        m = Mention(
                            source_type=raw.source_type,
                            source_url=raw.source_url,
                            country=raw.country,
                            language=raw.language,
                            published_at=raw.published_at,
                            collected_at=datetime.now(timezone.utc),
                            text_hash=th,
                            raw_text=raw.raw_text,
                            clean_text=sanitise_text(raw.raw_text),
                            author_id_hash=raw.author_id,
                            engagement_count=raw.engagement_count,
                            query_used=raw.query_used,
                            raw_metadata=raw.metadata or None,
                        )
                        db.add(m)
                        db.flush()
                    molecule_query = bool(inn) and (s in SUBSTANCE_SOURCES or s in SCIENTIFIC_SOURCES)
                    text = m.clean_text or m.raw_text or ""
                    if molecule_query:
                        existing_fanout = db.execute(
                            select(func.count()).select_from(MentionEntity).where(
                                MentionEntity.mention_id == m.id,
                                MentionEntity.entity_type == EntityType.brand,
                            )
                        ).scalar() or 0
                        if existing_fanout >= MAX_EVIDENCE_FANOUT:
                            continue  # non-specific (shared molecule) — skip
                        link_conf = 0.5  # evidence-class: molecule-level, not consumer
                    else:
                        if not text_mentions_brand(text, _brand_terms(brand.name)):
                            continue  # query returned something not about the brand
                        
                        if s in CONTEXT_GATED_SOURCES and is_namesake_gated(brand.name, brand.category):
                            extra = list(inn or []) + ([brand.manufacturer] if brand.manufacturer else [])
                            if not has_health_context(text, extra):
                                continue
                        link_conf = 0.9

                    if (brand.id, m.id) not in linked:
                        db.add(MentionEntity(
                            mention_id=m.id, entity_type=EntityType.brand,
                            entity_id=brand.id, confidence=link_conf,
                        ))
                        linked.add((brand.id, m.id))
                        kept += 1
                totals[s] += kept
                print(f"    {s:16s} +{kept}")
                db.commit()

        print("\n=== Done. New brand-linked mentions by source ===")
        for s in sources:
            print(f"  {s:16s} {totals[s]}")


if __name__ == "__main__":
    main()
