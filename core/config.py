from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": tolerate leftover/unknown keys in a deployment .env so a
    # stale var never crashes startup. Required fields below are still enforced.
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # ── Application ──────────────────────────────────────────────────────────
    APP_ENV: str = "development"
    APP_SECRET_KEY: str
    APP_ALLOWED_ORIGINS: str = "http://localhost:3000"

    LOG_LEVEL: str = "INFO"

    @property
    def allowed_origins(self) -> List[str]:
        return [o.strip() for o in self.APP_ALLOWED_ORIGINS.split(",")]

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str
    DATABASE_SYNC_URL: str

    # ── Redis ────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Qdrant ───────────────────────────────────────────────────────────────
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "pharmawatch_mentions"
    # Embedded fallback: when the Qdrant server at QDRANT_URL is unreachable
    # (e.g. Docker not running), the client falls back to an on-disk embedded
    # Qdrant store at this path so vectors are still persisted in Qdrant format.
    QDRANT_PATH: str = "data/qdrant_local"

    # ── OpenAI ───────────────────────────────────────────────────────────────
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-5.4-mini"
    AI_WEB_SEARCH: bool = True

    # ── YouTube ──────────────────────────────────────────────────────────────
    YOUTUBE_API_KEY: Optional[str] = None

    # ── GDPR / Compliance ────────────────────────────────────────────────────
    DPIA_PROCESSING_ENABLED: bool = False
    MENTION_RETENTION_DAYS: int = 90
    LAWFUL_BASIS: str = "legitimate_interest"

    # ── JWT ──────────────────────────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Embeddings (sentence-transformers for mention vectors) ───────────────
    EMBEDDING_MODEL: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

    # ── Supported markets (Phase 1: BE + FR) ─────────────────────────────────
    SUPPORTED_COUNTRIES: List[str] = ["BE", "FR"]
    SUPPORTED_LANGUAGES: List[str] = ["fr", "nl", "en", "de"]


settings = Settings()
