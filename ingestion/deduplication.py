import hashlib
from typing import Optional

from ingestion.connectors.base import RawMention


def compute_text_hash(mention: RawMention) -> str:
    """
    Compute a deduplication hash for a mention.
    Uses source_url + first 500 chars of raw_text so:
    - Same URL + same text = duplicate
    - Same URL + updated text = new version (different hash)
    - Different URL + same text = distinct entries (cross-posting OK to keep)
    """
    url_part = (mention.source_url or "").strip()
    text_part = mention.raw_text.strip()[:500]
    raw = f"{url_part}||{text_part}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_text_too_short(text: str, min_chars: int = 30) -> bool:
    return len(text.strip()) < min_chars


def sanitise_text(text: str) -> str:
    """Basic cleaning — remove excess whitespace, null bytes."""
    return " ".join(text.replace("\x00", "").split())
