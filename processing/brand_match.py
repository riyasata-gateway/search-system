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


PHARMA_CONTEXT_STEMS = frozenset({
    # core
    "pharmac", "medic", "medica", "medicin", "medicijn", "geneesmidd", "arznei",
    "apothe", "drug", "health", "sante", "gezond", "gesund", "vaccin", "impf",
    # forms / dosing
    "tablet", "comprime", "capsule", "gelule", "dosag", "posolog", "dosier",
    "cream", "creme", "ointment", "zalf", "salbe", "syrup", "sirop", "siroop",
    "supplement", "complement", "nahrungserg", "lozenge",
    # care / clinical
    "treatment", "traitement", "behandel", "therap", "patient", "clinic", "clinique",
    "klinik", "hospital", "hopital", "ziekenhuis", "krankenhaus", "prescription",
    "ordonnance", "recept", "rezept", "dermatolog", "cosmetic", "cosmetisch",
    "skincare", "skin care", "soin", "pharmacist", "pharmacien",
    # safety / conditions
    "symptom", "sympto", "disease", "maladie", "ziekte", "krankheit", "allerg",
    "side effect", "effet secondaire", "bijwerking", "nebenwirkung", "adverse",
    "recall", "rappel", "terugroep", "ruckruf", "infection", "cough", "toux",
    "hoest", "husten", "grippe", "griep", "nausea", "nausee", "rash",
    # regulators / market
    " fda", " ema", "emea", " otc", "riziv", "inami", "afmps", "fagg", "bcfi",
    # common molecules (so a bare "paracétamol / ibuprofène" headline qualifies
    # even without a generic pharma word)
    "paracetamol", "ibuprofen", "ibuprofene", "analges", "antacid", "heartburn",
    "brulure", "aspirin", "codeine",
    # dermocosmetic / beauty — a dermocosmetic brand's real news is beauty/retail,
    # not pharma vocabulary, so without these an ambiguous cosmetic name (Vichy,
    # Avène, La Roche-Posay) couldn't keep its genuine product news.
    "peau", "skin", "solaire", "sunscreen", "spf", "beaut", "schoonheid",
    "maquill", "makeup", "hydrat", "serum", "lotion", "shampoing", "shampoo",
    "hyaluron", "antiage", "anti-age", "moisturiz", "moisturis", "gommage",
    "nettoyant", "dermo", "eczema", "acne", "psoriasis", "gezichts", "hautpflege",
    "huidverzorg",
})

# Framework (curated) brand names that are ALSO a town / surname / common word and
# so attract non-pharma news despite being real brands — these are namesake-gated
# like supplier brands (the beauty/pharma context stems then keep their genuine
# product news and drop the town/politics/sport coverage). Folded, lowercased.
AMBIGUOUS_BRAND_NAMES = frozenset({
    "vichy",            # spa town + WWII regime
    "rennie",           # surname (e.g. rugby coach Dave Rennie)
    "la roche-posay",   # spa town (hippodrome, events)
    "avene",            # spa town (Avène-les-Bains)
})


def is_namesake_gated(name: str, category) -> bool:
    """True iff this brand's free-text news/social attribution must pass the
    pharma/health context gate: supplier-catalogue brands (no curated category)
    and the curated-but-ambiguous names above. Framework brands with coined names
    (Dafalgan, Eucerin, Mustela) are exempt — their bare-name news is trusted.
    """
    return category is None or _fold(name or "") in AMBIGUOUS_BRAND_NAMES


def has_health_context(text: str, extra_terms: List[str] | None = None) -> bool:
    """True iff `text` carries a pharma/health signal — a context stem, or one of
    `extra_terms` (the brand's molecule / manufacturer) as a whole token.

    Used to gate free-text news/social attribution: `text_mentions_brand` proves
    the *name* appears; this proves it's about the *pharma* brand, not a namesake.
    """
    if not text:
        return False
    hay = _fold(text)
    for stem in PHARMA_CONTEXT_STEMS:
        if stem in hay:
            return True
    for term in (extra_terms or []):
        t = _fold(term)
        if len(t) >= MIN_TERM_LEN and _term_pattern(t).search(hay):
            return True
    return False