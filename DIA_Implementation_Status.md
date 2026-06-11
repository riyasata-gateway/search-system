# DIA Framework — PharmaWatch Implementation Status

_Date: 2026-05-28 (Belgium+France localisation, EU pharmacovigilance, search audit)_
_Reference docs: `DIA_Pharma_Framework.docx`, `TDAH_DIA_Framework.docx`_

## Changelog 2026-05-28
- ✅ **Vector semantic search endpoint** wired (`/api/v1/search/semantic`)
- ✅ **Search audit tables** (`search_queries`, `search_results`, `ai_answers`) + Alembic `c3d4e5f6a7b8`; every `/live`, `/ai`, `/semantic` call persisted via BackgroundTasks
- ✅ **Azure Blob references removed** (Postgres + Qdrant only)
- ✅ **Belgium+France localisation** — locale map narrowed to BE+FR; Wikipedia/News grounding focused on `["BE","FR"]` × `["fr","nl","de","en"]`
- ✅ **YouTube activated** — `collect-youtube-6h` Celery beat + added to live-search defaults
- ✅ **EudraVigilanceConnector** replaces openFDA as default EU pharmacovigilance source (openFDA still available opt-in via `?sources=openfda`)
- ✅ **BelgiumHealthDataConnector** scaffold — BCFI/CBIP + FAGG shortages + data.gov.be (selector tuning needed)
- ✅ **BelgiumHCPConnector** scaffold — FAMHP pharmacy list + INAMI/RIZIV lookup + Doctena BE (INAMI endpoint URL needs re-verification)
- ✅ **DoctissimoConnector** — ToS-respecting (no /search/ hammering, HMAC author pseudonymisation, 6s throttle), DPIA-gated
- ✅ **DrugsComConnector** — permanent disabled stub (ToS prohibits automated access; documented in code)

## Framework recap

**DIA = Data → Intelligence → Action**, run as a continuous flywheel (each action creates new signals).
**TDAH** (Trend Data Aggregator Hyperintelligent) is Datatopia's first DIA-built product, focused on **brand trend detection + Brand Potential Index + prescriptive recommendations** for EU pharma (BE/FR phase 1).

The frameworks specify three layers with concrete components — each component has been mapped to the codebase below.

---

## ✅ PART 1 — Already Implemented

### D · DATA / DETECT (collection layer)

| Component | Status | Location |
|---|---|---|
| Social Media (Reddit) | ✅ | `ingestion/connectors/reddit.py` |
| Google Trends | ✅ | `ingestion/connectors/google_trends.py` |
| Forums | ✅ | `ingestion/connectors/forum_scraper.py` |
| YouTube (Live Search + ingestion) | ✅ | `ingestion/connectors/youtube.py` + wired in `live_search.py` |
| News & Press | ✅ | `ingestion/connectors/rss_news.py` |
| Pharmacy inventory/sales | ✅ | `ingestion/connectors/pharmacy_import.py` |
| **Wikipedia (multilingual reference)** | ✅ | `ingestion/connectors/wikipedia.py` |
| **PubMed (biomedical literature)** | ✅ | `ingestion/connectors/pubmed.py` |
| **ClinicalTrials.gov (trial registry)** | ✅ | `ingestion/connectors/clinical_trials.py` |
| **openFDA (drug labels + FAERS adverse events)** | ✅ (opt-in fallback) | `ingestion/connectors/openfda.py` |
| **EudraVigilance EU-direct pull** | ✅ | `ingestion/connectors/eudravigilance.py` — adrreports.eu, EEA-wide |
| **Belgium health-data multi-source** | ⚠️ Scaffold | `ingestion/connectors/belgium_health_data.py` — BCFI/CBIP, FAGG shortages, data.gov.be |
| **Belgium HCP discovery** | ⚠️ Scaffold | `ingestion/connectors/belgium_hcp.py` — FAMHP, INAMI, Doctena |
| **Doctissimo patient forums (FR/BE)** | ✅ (DPIA-gated) | `ingestion/connectors/doctissimo.py` |
| **Drugs.com** | ❌ Disabled (ToS) | `ingestion/connectors/drugs_com.py` — permanent stub |
| **Search audit log** | ✅ | `core/search_audit.py`, tables `search_queries` / `search_results` / `ai_answers` |
| **Vector semantic search** | ✅ | `/api/v1/search/semantic` — Qdrant read path |
| **App Store reviews (ToS-safe patient reviews)** | ✅ | `ingestion/connectors/app_store.py` |
| **Trustpilot reviews (consumer reviews via API)** | ✅ | `ingestion/connectors/trustpilot.py` (requires `TRUSTPILOT_API_KEY`) |
| **Real-time streaming ingestion** ("aucun signal ne se perd") | ✅ | `core/event_bus.py`, `workers/streaming_worker.py`, beat schedule 60s pulse |
| **Market data import scaffolding** (IQVIA / GERS / IMS CSV) | ✅ | `models/market_data.py`, `api/routers/market_data.py` |
| **Prescription event import scaffolding** (de-identified Rx CSV) | ✅ | `models/market_data.PrescriptionEvent`, HMAC-pseudonymised |
| Licensed API (stub) | ✅ | `ingestion/connectors/licensed_api.py` |
| Deduplication + scheduling | ✅ | `ingestion/deduplication.py`, `workers/ingestion_worker.py` |
| Quantitative + qualitative dual approach | ✅ | engagement counts + NLP classification |
| Multi-locale (BE/FR/NL/DE) | ✅ | language detection + translation pipeline |

### I · INTELLIGENCE / INTERPRET (processing layer)

| Component | Status | Location |
|---|---|---|
| Trend Detection (abs + %) | ✅ | `intelligence/trend_engine.py` |
| Sentiment NLP | ✅ | `processing/sentiment.py` |
| Entity Resolution (brand/molecule) | ✅ | `processing/entity_resolution.py` |
| Topic / Intent classification | ✅ | `processing/topic_classifier.py` |
| Risk Detection (5 types) | ✅ | `processing/risk_detector.py` |
| Share of Voice (basic) | ✅ | `intelligence/share_of_voice.py` |
| Vector / semantic search (Qdrant) | ✅ | `processing/embeddings.py` |
| Cross-lingual query expansion | ✅ | `processing/query_expansion.py` |
| LLM weekly summarisation | ✅ | `intelligence/llm_summariser.py` |
| **Brand Potential Index** (Awareness × Adoption × Sentiment × MarketFit) | ✅ | `intelligence/brand_potential_index.py` |
| **Momentum Scoring** (velocity + acceleration) | ✅ | `intelligence/momentum.py` |
| **Anomaly Detection** (z-score statistical baseline) | ✅ | `intelligence/anomaly.py` |
| **Lifecycle Stage classifier** (pre-launch / launch / growth / maturity / decline) | ✅ | `intelligence/lifecycle.py` |
| **Output normalisation** to ABS / PERCENT / SCORE envelope | ✅ | `intelligence/output_schema.py` |

### A · ACTION / ACT (prescriptive layer)

| Component | Status | Location |
|---|---|---|
| Pharmacist Recommender (trend × inventory × velocity) | ✅ | `intelligence/pharmacist_recommender.py` |
| Pharmacist Dashboard | ✅ | `frontend/src/pages/PharmacistDashboard.tsx` |
| Lab/Brand Dashboard | ✅ | `api/routers/lab.py`, `frontend/src/pages/LabDashboard.tsx` |
| Alert Engine (shortage, risk, misinformation…) | ✅ | `intelligence/alert_engine.py`, `api/routers/alerts.py` |
| Adverse Event Review queue (HITL) | ✅ | `api/routers/adverse_events.py` |
| AI Search with citations | ✅ | `api/routers/ai_search.py` |
| Live Search (no-write, real-time, 10 sources) | ✅ | `api/routers/live_search.py` |
| **OTC Counseling Tips generator** (LLM, trend-grounded) | ✅ | `intelligence/counseling_tips.py` |
| **Patient Q&A Scripts** (auto-generated, guard-railed) | ✅ | `intelligence/counseling_tips.py` |
| **Substitution Guidance engine** (shortage / competitor-triggered) | ✅ | `intelligence/substitution.py` |
| **Action Telemetry / Flywheel closure** | ✅ | `intelligence/flywheel.py`, `models/action_event.py` |
| **Launch Readiness Score** (BPI × Lifecycle × Anomaly × Safety × Freshness) | ✅ | `intelligence/launch_readiness.py` |
| **Key Message Tuning** (topic × sentiment × engagement resonance) | ✅ | `intelligence/key_message.py` |
| **Campaign Pivot recommendations** (signal-triggered) | ✅ | `intelligence/campaign_pivot.py` |
| **HCP Targeting** (interface, graceful no-data path) | ⚠️ Stub | `intelligence/hcp_targeting.py` — awaits KOL data source |
| **Next-Best-Action orchestrator** (composes all Phase 1+2 modules, flywheel-weighted) | ✅ | `intelligence/next_best_action.py` |
| **Brand Potential UI surface** (BPI, momentum, lifecycle, key msgs, pivots, NBA queue) | ✅ | `frontend/src/pages/BrandPotential.tsx` |
| **Intelligence API router** (BPI, momentum, anomaly, lifecycle, counseling, substitutes, flywheel, launch-readiness, key-messages, pivots, hcp, NBA) | ✅ | `api/routers/intelligence.py` |

### Cross-cutting (foundation)

- ✅ RBAC (pharmacist / lab_user / admin), JWT auth, audit log
- ✅ GDPR endpoints — Art. 15 / 17 / 20 (`gdpr/`, `api/routers/gdpr.py`)
- ✅ Pseudonymisation (HMAC author IDs), retention sweeps
- ✅ DPIA — v2.0 **final-sign-off-ready** (`gdpr/dpia.md`) — all 19 processing activities, residual-risk register R1-R12, conditions-precedent checklist, signature block
- ✅ TDAH product branding pass (Login, Layout, FastAPI title, AI prompts, alert emails, page title)
- ✅ React frontend, EN/FR/NL/DE i18n
- ✅ Postgres + Qdrant + Celery/Redis + FastAPI stack
- ✅ Sync + async SQLAlchemy session helpers (`core/database.py`)

---

## ❌ PART 2 — To Be Done

### D · DATA gaps — narrower set (remaining items are mostly commercial / regulatory)

| Component | Why it matters | Effort | Blocker |
|---|---|---|---|
| ✅ Patient Reviews (App Store + Trustpilot) | DONE — ToS-safe surfaces wired | — | — |
| ⚠️ Patient Reviews (Drugs.com, Doctissimo deep crawl) | Deeper qualitative coverage | M | ToS / scraping ethics |
| **HCP Feedback channel** (Doctolib, LinkedIn medical) | Distinct from generic social | M | API access & consent |
| ✅ Real-time streaming ingestion | DONE — bus + 60s pulse + SSE | — | — |
| ⚠️ Market Data — actual data load | Schema + import endpoint ready; awaits feed | L | Commercial contracts (IQVIA / GERS / IMS) |
| ⚠️ EHR / Prescription data — actual data load | Schema + import endpoint ready; awaits feed | L | Regulatory + commercial |
| **Field Force CRM integration** (Veeva, Salesforce HC) | Required for HCP targeting | L | Commercial contracts |
| **Search Intent data** (paid keyword tools) | TDAH source | S | Subscription |
| **EudraVigilance EU-direct pull** | Currently relying on openFDA (US) for pharmacovigilance | M | API access |

### I · INTELLIGENCE remaining gaps

| Component | Status | Notes |
|---|---|---|
| **Competitor Benchmarking** (full) | ⚠️ Partial | Only mention-count SOV today; BPI gives a richer competitor read but no head-to-head matrix |
| **Rx Pattern Mining** | ❌ | Blocked on Rx data ingestion |
| **KOL Signal Mapping** | ❌ | No HCP graph / influence model — needs HCP data source |
| **Cluster Segmentation** | ❌ | Audience or topic clustering — ML model needed |

### A · ACTION gaps — brand-facing prescriptive layer

**For pharma brands — remaining gaps:**
- ✅ **Launch Readiness Score** — DONE
- ✅ **Key Message Tuning** — DONE
- ⚠️ **HCP Targeting by prescriber momentum** — interface shipped; awaits KOL data source
- ✅ **Campaign Pivot recommendations** — DONE
- ❌ **MSL Deployment guidance** (geo + KOL ranked) — needs HCP data
- ⚠️ **Weak signal detection before competitors** — Anomaly + Momentum modules surface this today; dedicated alert/notification surface for proactive detection still missing

**Orchestration:**
- ✅ **Next-Best-Action engine** — DONE (composes BPI, Launch Readiness, Campaign Pivot, Key Messages, HCP Targeting, flywheel-weighted)

### Cross-cutting / productisation

- ✅ TDAH product branding pass — DONE (`frontend/index.html`, `Layout.tsx`, `Login.tsx`, `api/main.py`, AI/counseling prompts, alert email subjects)
- ✅ Brand Potential Index dedicated UI surface — DONE (`frontend/src/pages/BrandPotential.tsx`)
- ✅ Real-time push (SSE) for mentions / alerts / signals — DONE (`api/routers/stream.py`, `frontend/src/hooks/useLiveStream.ts`, live pill in Layout, live ticker on Brand Potential)
- ✅ DPIA — v2.0 final-sign-off-ready — DONE (`gdpr/dpia.md`); awaits ink from DPO + Legal + CISO + PO + Eng Lead
- ❌ Production deploy configs (Azure Functions for Beat schedule, etc.)

---

## Suggested phasing (PM view) — updated

### ✅ Phase 1 — Intelligence layer closure (DONE)
1. ✅ Brand Potential Index formula + API
2. ✅ Momentum Scoring + Anomaly Detection
3. ✅ Lifecycle Stage classifier
4. ✅ Output normalisation to ABS / % / SCORE
5. ✅ Action telemetry → flywheel closure (model + API + weight-back into recommender)

### ✅ Phase 2 — Brand-facing actions (DONE this iteration)
1. ✅ Launch Readiness Score (BPI × Lifecycle × Anomaly × Safety × Freshness)
2. ✅ Key Message Tuning + Campaign Pivot recos (signal-triggered, uses anomaly + flywheel weights)
3. ⚠️ HCP Targeting — interface ready, awaits KOL data source (Phase 3 dependency)
4. ✅ Next-Best-Action orchestrator (composes BPI, Launch Readiness, Pivots, Key Messages, HCP — flywheel-weighted)
5. ✅ Brand Potential UI surface (`frontend/src/pages/BrandPotential.tsx`)

### ✅ Phase 3 — Data depth + real-time streaming (DONE this iteration)
1. ✅ ClinicalTrials.gov + ✅ PubMed
2. ✅ openFDA — pharmacovigilance entry point
3. ✅ Patient review platforms (App Store official RSS + Trustpilot API)
4. ✅ Real-time streaming ingestion (Redis pub/sub bus + 60s pulse + SSE endpoints + frontend live indicator)
5. ✅ Market data + Rx data import scaffolding (schema + CSV import endpoint; awaits real commercial feeds)

### Phase 4 — Productisation (partial)
1. ✅ TDAH branding pass (DONE)
2. ✅ Real-time SSE alerts (DONE in Phase 3)
3. ✅ DPIA v2.0 finalised — awaits DPO/Legal ink (DONE code-side)
4. ❌ Production deploy configs (Azure Functions for Beat schedule, container build, secrets management)
5. ❌ Email/Slack alert fan-out from SSE bus

---

## Headline summary — updated

| Layer | Coverage | Comment |
|---|---|---|
| **D · Data** | ~95% | 13+ sources live + Patient Reviews (App Store + Trustpilot) + real-time streaming bus (`events:mentions`, `events:alerts`, `events:signals`). Market data / Rx schema + CSV import live; awaits commercial feed contracts. |
| **I · Intelligence** | ~90% | All core analytics present. Rx mining + KOL graph + audience clustering remain. |
| **A · Action** | ~90% | Pharmacist + brand-side both built. HCP Targeting awaits KOL data. |
| **Flywheel closure** | ~90% | Telemetry log + acceptance-weight feedback live; NBA UI logs every decision back; SSE bus emits new mentions live. |
| **Real-time** | ~85% | SSE endpoints + browser hook + live indicator in UI. Push notification surfaces (email/Slack) still TODO. |

**Remaining biggest gap**: actual commercial feed contracts (IQVIA / GERS / Veeva / EHR Rx) to load the schema we just shipped — code is no longer the blocker.

**API surface (mounted at `/api/v1/intelligence`)**:
Phase 1:
- `GET  /api/v1/intelligence/bpi/{brand_id}`
- `GET  /api/v1/intelligence/bpi`
- `GET  /api/v1/intelligence/momentum/{entity_type}/{entity_id}`
- `GET  /api/v1/intelligence/momentum`
- `GET  /api/v1/intelligence/anomalies`
- `GET  /api/v1/intelligence/lifecycle/{entity_type}/{entity_id}`
- `GET  /api/v1/intelligence/counseling/{product_id}`
- `GET  /api/v1/intelligence/substitutes/{product_id}`
- `POST /api/v1/intelligence/flywheel/log`
- `GET  /api/v1/intelligence/flywheel/acceptance`

Phase 2:
- `GET  /api/v1/intelligence/launch-readiness/{brand_id}`
- `GET  /api/v1/intelligence/launch-readiness`
- `GET  /api/v1/intelligence/key-messages/{brand_id}`
- `GET  /api/v1/intelligence/campaign-pivots/{brand_id}`
- `GET  /api/v1/intelligence/hcp-targeting/{brand_id}` (graceful no-data path)
- `GET  /api/v1/intelligence/next-best-action/{brand_id}`

Phase 3 (new):
- `GET  /api/v1/stream/mentions` — SSE stream of new mentions (token via ?token=)
- `GET  /api/v1/stream/alerts` — SSE stream of new alerts
- `GET  /api/v1/stream/signals` — SSE stream of anomaly + momentum signals
- `POST /api/v1/market-data/imports/market-data` — IQVIA/GERS/IMS CSV upload (admin)
- `POST /api/v1/market-data/imports/prescriptions` — de-identified Rx CSV upload (admin)
- `GET  /api/v1/market-data/imports` — audit log of imports

**Frontend**:
- `/brand-potential` route — Brand Potential surface with live ticker
- `useLiveStream` hook + LiveStatusPill in `Layout.tsx`

**Workers (new)**:
- `stream-news-pulse-60s` — 60-second news pulse
- `stream-forums-pulse-5min` — 5-minute forum pulse
- `sweep-anomalies-5min` + `sweep-momentum-15min` — push signal events when thresholds cross

**Migrations to run**: `alembic upgrade head`
- `a1f2d3e4b5c6` — `action_events` (Phase 1 flywheel)
- `b2e3f4a5c6d7` — `market_data` + `prescription_events` + `market_data_imports` (Phase 3)
