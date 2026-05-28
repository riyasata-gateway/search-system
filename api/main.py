from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from core.config import settings
from core.logging import configure_logging
from core.redis_client import close_redis

from api.routers import (
    auth,
    brands,
    products,
    ingestion,
    mentions,
    trends,
    pharmacist,
    lab,
    alerts,
    adverse_events,
    search_topics,
    admin,
    gdpr,
    live_search,
    ai_search,
    intelligence,
    stream,
    market_data,
)

configure_logging()

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_redis()


app = FastAPI(
    title="TDAH API",
    description=(
        "TDAH — Trend Data Aggregator Hyperintelligent. "
        "DIA-built (Data → Intelligence → Action) brand-potential and pharma "
        "trend engine for the EU market. By PharmaWatch."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(brands.router, prefix="/api/v1/brands", tags=["brands"])
app.include_router(products.router, prefix="/api/v1/products", tags=["products"])
app.include_router(search_topics.router, prefix="/api/v1/search-topics", tags=["search-topics"])
app.include_router(ingestion.router, prefix="/api/v1/ingestion", tags=["ingestion"])
app.include_router(mentions.router, prefix="/api/v1/mentions", tags=["mentions"])
app.include_router(trends.router, prefix="/api/v1/trends", tags=["trends"])
app.include_router(pharmacist.router, prefix="/api/v1/pharmacist", tags=["pharmacist"])
app.include_router(lab.router, prefix="/api/v1/lab", tags=["lab"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["alerts"])
app.include_router(adverse_events.router, prefix="/api/v1/adverse-events", tags=["adverse-events"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(gdpr.router, prefix="/api/v1/gdpr", tags=["gdpr"])
app.include_router(live_search.router, prefix="/api/v1/search", tags=["search"])
app.include_router(ai_search.router, prefix="/api/v1/search", tags=["search"])
app.include_router(intelligence.router, prefix="/api/v1/intelligence", tags=["intelligence"])
app.include_router(stream.router, prefix="/api/v1/stream", tags=["stream"])
app.include_router(market_data.router, prefix="/api/v1/market-data", tags=["market-data"])


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok", "version": "1.0.0"}
