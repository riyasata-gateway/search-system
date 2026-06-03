from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

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

    # ── LLM ──────────────────────────────────────────────────────────────────
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "mistral:7b-instruct"

    # ── OpenAI ───────────────────────────────────────────────────────────────
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-5.4-mini"
    AI_WEB_SEARCH: bool = True

    # ── Reddit ───────────────────────────────────────────────────────────────
    REDDIT_CLIENT_ID: Optional[str] = None
    REDDIT_CLIENT_SECRET: Optional[str] = None
    REDDIT_USER_AGENT: str = "pharmawatch/1.0"

    # ── YouTube ──────────────────────────────────────────────────────────────
    YOUTUBE_API_KEY: Optional[str] = None

    # ── Trustpilot (Phase 3 patient-review source) ───────────────────────────
    TRUSTPILOT_API_KEY: Optional[str] = None

    # ── Licensed social API (Tier 3) ─────────────────────────────────────────
    LICENSED_API_PROVIDER: Optional[str] = None
    LICENSED_API_KEY: Optional[str] = None
    LICENSED_API_BASE_URL: Optional[str] = None

    # ── Google Trends ────────────────────────────────────────────────────────
    GOOGLE_TRENDS_PROXY: Optional[str] = None

    # ── GDPR / Compliance ────────────────────────────────────────────────────
    DPIA_PROCESSING_ENABLED: bool = False
    MENTION_RETENTION_DAYS: int = 90
    AGGREGATE_RETENTION_DAYS: int = 730
    LAWFUL_BASIS: str = "legitimate_interest"

    # ── JWT ──────────────────────────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Rate limiting ────────────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 60

    # ── NLP models ───────────────────────────────────────────────────────────
    HF_CACHE_DIR: str = ".cache/huggingface"
    SENTIMENT_MODEL: str = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
    TOPIC_MODEL: str = "facebook/bart-large-mnli"
    EMBEDDING_MODEL: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    TRANSLATION_MODEL_PREFIX: str = "Helsinki-NLP/opus-mt"

    # ── Notifications (adverse event routing) ────────────────────────────────
    PHARMACOVIGILANCE_EMAIL: str = "pharmacovigilance@yourorg.com"
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: str = "noreply@pharmawatch.eu"

    # ── Supported markets (Phase 1: BE + FR) ─────────────────────────────────
    SUPPORTED_COUNTRIES: List[str] = ["BE", "FR"]
    SUPPORTED_LANGUAGES: List[str] = ["fr", "nl", "en", "de"]

    # ── OTC categories (Phase 1) ─────────────────────────────────────────────
    OTC_CATEGORIES: List[str] = [
        "pain_relief",
        "digestive",
        "allergy",
        "vitamins_supplements",
        "dermatology_otc",
    ]



settings = Settings()
