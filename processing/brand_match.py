"""Shared brand ↔ text matching — the relevance gate for entity attribution.

The product's value is correct data. A mention may only be attributed to a brand
as a *consumer/brand* signal when the brand (or one of its trade-name terms)
actually appears in the text — matched on WORD BOUNDARIES, not raw substring
(`"roc" in "maroc"` is the class of bug this replaces).

Two helpers:
  • brand_terms(name)        — the searchable trade-name term(s) for a brand,
                               splitting composite labels the same way the
                               ingestion search does.
  • text_mentions_brand(...) — True iff any term occurs as a whole token in text.

Accent- and case-folded so "Hydraphase" matches "hydraphase" and "Eucerïn"≈"Eucerin".
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import List

# Terms shorter than this are too collision-prone to trust on their own
# (2–3 char brand codes match acronyms everywhere). They still attribute via the
# review `brand_name` exact path; they just can't claim a free-text mention.
MIN_TERM_LEN = 4


def _fold(s: str) -> str:
    """Lowercase + strip diacritics + drop ®/™ so matching is robust."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace("®", "").replace("™", "").strip()


def brand_terms(name: str) -> List[str]:
    """Trade-name term(s) for a brand. Mirrors the ingestion query splitter:
    'UCB brands (Keppra, Bimzelx)' → ['Keppra', 'Bimzelx']; 'A/B' → ['A','B']."""
    if not name:
        return []
    if "(" in name and ")" in name:
        inside = name[name.find("(") + 1:name.rfind(")")]
        parts = [p.strip() for p in inside.split(",") if p.strip()]
        if parts:
            return parts
    if "/" in name:
        return [p.strip() for p in name.split("/") if p.strip()]
    return [name]


@lru_cache(maxsize=8192)
def _term_pattern(term_folded: str):
    # Whole-token match: the term may itself contain spaces/hyphens, so we bound
    # the whole phrase with non-word lookarounds rather than \b on every char.
    return re.compile(rf"(?<!\w){re.escape(term_folded)}(?!\w)")


def text_mentions_brand(text: str, terms: List[str], *, min_len: int = MIN_TERM_LEN) -> bool:
    """True iff any trade-name term appears as a whole token in `text`.

    Terms shorter than `min_len` are ignored (too collision-prone). Returns False
    on empty text/terms — i.e. "we cannot confirm this is about the brand".
    """
    if not text or not terms:
        return False
    hay = _fold(text)
    for term in terms:
        t = _fold(term)
        if len(t) < min_len:
            continue
        if _term_pattern(t).search(hay):
            return True
    return False