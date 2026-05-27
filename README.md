# PharmaWatch — EU Pharmaceutical Brand Intelligence Engine

A Brandwatch-style social listening and pharmacy sales intelligence platform for the EU pharmaceutical industry, covering Belgium and France (Phase 1). Supports French, Dutch, English, and German.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    React Frontend (Vite)                 │
│  Login · Pharmacist Dashboard · Lab Dashboard · Alerts  │
│  Adverse Event Review · Brand Setup · Admin             │
└──────────────────────┬──────────────────────────────────┘
                       │ REST /api/v1
┌──────────────────────▼──────────────────────────────────┐
│               FastAPI  (RBAC · Rate limiting)            │
│  auth · brands · products · search_topics · ingestion   │
│  mentions · trends · pharmacist · lab · alerts          │
│  adverse_events · admin · gdpr                          │
└──────┬────────────────────────────────────┬─────────────┘
       │ SQLAlchemy async                   │ Celery tasks
┌──────▼───────┐  ┌──────────┐  ┌──────────▼──────────────┐
│ PostgreSQL   │  │  Qdrant  │  │    Celery + Redis        │
│ (Alembic)   │  │ (vectors)│  │  ingestion · NLP · recs  │
└──────────────┘  └──────────┘  └─────────────────────────┘
       │                                    │
       └──────────── Ollama (LLM) ──────────┘
```

---

## Modules

| Layer | Path | Purpose |
|---|---|---|
| API | `api/` | FastAPI routers, RBAC, audit logging |
| Ingestion | `ingestion/` | Connectors: Google Trends, Reddit, RSS, Forums, YouTube, Licensed APIs, Pharmacy files |
| NLP | `processing/` | Language detection, translation, entity resolution, sentiment, topic/intent, risk detection, embeddings |
| Intelligence | `intelligence/` | Trend engine, share of voice, pharmacist recommender, alert engine, lab insights, LLM summariser |
| Workers | `workers/` | Celery app, ingestion worker, NLP processing worker |
| Models | `models/` | SQLAlchemy ORM models |
| GDPR | `gdpr/` | Data subject rights (access, erasure, portability), DPIA |
| Migrations | `migrations/` | Alembic migrations |
| Data | `data/pharma_dictionary/` | Seed CSVs for brands, products, aliases |
| Frontend | `frontend/` | React 18 + Vite + TailwindCSS + Recharts |

---

## Prerequisites

- Docker + Docker Compose
- Python 3.11+
- Node.js 20+ (frontend only)

---

## Local Development Setup

### 1. Clone and configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set:
#   DATABASE_URL, DATABASE_SYNC_URL, APP_SECRET_KEY
#   DPIA_PROCESSING_ENABLED=true  (required to enable ingestion)
```

### 2. Start infrastructure services

```bash
docker-compose up -d db redis qdrant ollama
```

### 3. Install Python dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 4. Run database migrations

```bash
alembic upgrade head
```

### 5. Seed the pharma dictionary

```bash
python scripts/seed_pharma_dictionary.py
```

### 6. Start the API

```bash
uvicorn main:app --reload --port 8000
```

### 7. Start Celery worker (separate terminal)

```bash
celery -A workers.celery_app worker --loglevel=info
```

### 8. Start Celery beat (local scheduling — separate terminal)

```bash
celery -A workers.celery_app beat --loglevel=info
```

### 9. Start the frontend

```bash
cd frontend
npm install
npm run dev
# Opens at http://localhost:3000
```

### Full stack via Docker Compose

```bash
docker-compose up --build
```

---

## Running Tests

```bash
# Unit tests (no DB required)
pytest tests/unit/ -m unit

# Integration tests (requires test DB running)
pytest tests/integration/ -m integration

# All tests
pytest
```

---

## API Documentation

Interactive Swagger UI: `http://localhost:8000/docs`  
ReDoc: `http://localhost:8000/redoc`

---

## Key Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | Async PostgreSQL URL | — |
| `DATABASE_SYNC_URL` | Sync PostgreSQL URL (Alembic, Celery) | — |
| `REDIS_URL` | Redis broker/backend URL | `redis://localhost:6379/0` |
| `APP_SECRET_KEY` | JWT signing key + HMAC pseudonymisation key | — |
| `DPIA_PROCESSING_ENABLED` | **Must be `true` to enable any ingestion** | `false` |
| `MENTION_RETENTION_DAYS` | Days to retain raw mention text (GDPR) | `90` |
| `REDDIT_CLIENT_ID` | Reddit API credentials (optional) | — |
| `YOUTUBE_API_KEY` | YouTube Data API v3 key (optional) | — |
| `PHARMACOVIGILANCE_EMAIL` | Email for adverse event notifications | — |
| `OLLAMA_MODEL` | LLM model for weekly summaries | `mistral:7b-instruct` |

See `.env.example` for the full list.

---

## GDPR Compliance

- **Pseudonymisation**: author IDs are HMAC-SHA256 hashed at ingestion (never stored in plaintext)
- **Retention**: raw mention text auto-deleted after `MENTION_RETENTION_DAYS` via daily Celery task
- **Data subject rights**: Art. 15 (access), 17 (erasure), 20 (portability) implemented at `POST /api/v1/gdpr/{access,erasure,portability}` (admin only)
- **Adverse events**: all candidates require human pharmacovigilance review — no automated decisions
- **Scraping policy**: each data source has `is_scraping_allowed` and `robots_txt_checked` flags
- **DPIA**: see `gdpr/dpia.md` — requires DPO sign-off before production launch

---

## Production Deployment (Azure)

1. Use **Azure Database for PostgreSQL Flexible Server** (West Europe)
2. Use **Azure Cache for Redis**
3. Use **Azure Blob Storage** for raw file exports (`AZURE_STORAGE_CONNECTION_STRING`)
4. Deploy API via **Azure Container Apps** or **Azure App Service**
5. Deploy Celery workers via **Azure Container Instances**
6. Replace Celery Beat with **Azure Functions Timer Triggers** for each ingestion task
7. Store secrets in **Azure Key Vault** — reference via environment variables
8. All infrastructure must remain in **EU/EEA region** (GDPR data residency)

---

## Sprint Roadmap

| Sprint | Status | Scope |
|---|---|---|
| 0 | ✅ Complete | Project structure, models, Alembic, API scaffolding |
| 1 | ✅ Complete | Ingestion connectors, deduplication, Celery tasks |
| 2 | ✅ Complete | NLP pipeline (lang detect, translation, entity resolution, sentiment, topic, risk, embeddings) |
| 3 | ✅ Complete | Intelligence layer (trends, SOV, recommender, alerts, lab insights, LLM summary) |
| 4 | ✅ Complete | API wiring with RBAC, audit logs, GDPR endpoints |
| 5 | ✅ Complete | React frontend dashboards |
| 6 | ✅ Complete | GDPR automation, DPIA, Alembic migration, seed data, hardening |

---

## Compliance Notes

- **No automated medical advice**: the system provides signals and recommendations for human review only
- **No prescription medicine promotion generation**: `is_prescription_promotion` flag triggers human review
- **No unrestricted scraping**: all web sources require explicit `is_scraping_allowed=True` and `robots_txt_checked=True`
- **Pharmacovigilance**: adverse event candidates are routed to qualified reviewers via email alert; no automated EU PSUR/ICSR filing
