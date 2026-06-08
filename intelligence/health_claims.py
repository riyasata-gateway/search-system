"""EU health-claims substantiation lookup (for the NUT / supplement category).

Loads the EU Register of nutrition & health claims (built by
`scripts/load_health_claims.py` → `data/eu_health_claims.json`) and answers, for
a given food-supplement brand, how much of what it's associated with is backed by
an EU-AUTHORISED health claim vs only non-authorised claims.

Brands carry no ingredient list in our DB, so we derive the substances from the
text we DO have — the brand name plus its linked pharmacy-review / retail text —
by scanning for register substances. It's a proxy (honest about that), but it
turns the register into a real per-brand signal for the otherwise data-thin NUT
category instead of leaving every supplement KPI empty.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from functools import lru_cache
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "eu_health_claims.json")

# Substance tokens too generic to match safely against free text.
_GENERIC = {"water", "food", "foods", "protein", "proteins", "fat", "fats",
            "energy", "carbohydrate", "carbohydrates", "fibre", "fiber", "sugar",
            "sugars", "salt", "starch", "meal", "diet", "plant", "plants",
            "fruits", "vegetables", "cholesterol", "lactose", "fruit", "vegetable"}


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s or "")
                if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def _match_token(substance: str) -> Optional[str]:
    """The normalised core term to look for in brand text (drops parentheticals)."""
    core = substance.split("(")[0]
    tok = _norm(core)
    if len(tok) < 4 or tok in _GENERIC:
        return None
    return tok


@lru_cache(maxsize=1)
def _index() -> Dict:
    """{token -> {'display':str, 'authorised':bool, 'sample_claim':str}} + token list."""
    try:
        with open(_PATH, encoding="utf-8") as fh:
            rows = json.load(fh)
    except FileNotFoundError:
        return {"by_token": {}, "tokens": []}

    by_token: Dict[str, dict] = {}
    for r in rows:
        tok = _match_token(r["substance"])
        if not tok:
            continue
        entry = by_token.setdefault(tok, {
            "display": r["substance"].split("(")[0].strip(),
            "authorised": False,
            "sample_claim": "",
        })
        if r["status"] == "authorised":
            entry["authorised"] = True
            if r.get("claim") and not entry["sample_claim"]:
                entry["sample_claim"] = r["claim"]
    # Longer tokens first so "vitamin d" matches before "vitamin".
    tokens = sorted(by_token, key=len, reverse=True)
    return {"by_token": by_token, "tokens": tokens}


# French→English substance synonyms — the register stores English substance
# names ("Vitamin D") but the brand's reviews/retail text is largely French
# ("vitamine D", "fer", "magnésium"). Normalising these lifts NUT match coverage.
_FR_SYN = [
    ("vitamine", "vitamin"), ("fer", "iron"), ("cuivre", "copper"),
    ("magnesium", "magnesium"), ("calcium", "calcium"), ("zinc", "zinc"),
    ("acide folique", "folate"), ("iode", "iodine"), ("selenium", "selenium"),
    ("proteines", "protein"), ("fibres", "fibre"), ("probiotiques", "probiotic"),
]


def substances_in_text(blob: str) -> List[str]:
    """Register substance tokens present in `blob` (whole-word, normalised)."""
    idx = _index()
    if not idx["tokens"]:
        return []
    norm = _norm(blob)
    for fr, en in _FR_SYN:
        if fr != en:
            norm = norm.replace(fr, en)
    hay = f" {norm} "
    found = []
    for tok in idx["tokens"]:
        if f" {tok} " in hay:
            found.append(tok)
    return found


def substantiation_for_brand(db: Session, brand) -> Optional[Dict]:
    """Claim-substantiation signal for a NUT brand, or None if nothing matched.

    Scans the brand name + a sample of its linked review/retail text for register
    substances and reports how many carry an EU-authorised claim.
    """
    # Brand name + a bounded sample of linked-mention text (reviews/retail/news).
    parts: List[str] = [brand.name or ""]
    rows = db.execute(text("""
        SELECT coalesce(m.clean_text, m.raw_text) AS t
        FROM mention_entities me JOIN mentions m ON m.id = me.mention_id
        WHERE me.entity_type = 'brand' AND me.entity_id = :bid
          AND m.source_type IN ('farmaline','medimarket','rss','news','brand_site','wikipedia')
        LIMIT 400
    """), {"bid": brand.id}).fetchall()
    parts.extend((r[0] or "")[:500] for r in rows)
    blob = " . ".join(parts)

    matched = substances_in_text(blob)
    if not matched:
        return None

    idx = _index()["by_token"]
    authorised = [t for t in matched if idx[t]["authorised"]]
    n, a = len(matched), len(authorised)
    pct = round(100 * a / n) if n else 0
    # Peer-style list for the UI: substance + whether it's EU-authorised.
    peers = [{"name": idx[t]["display"],
              "share": 100 if idx[t]["authorised"] else 0,
              "is_self": False} for t in matched[:8]]
    return {
        "value": pct,
        "display": f"{a}/{n} substances EU-authorised",
        "detail": (f"{a} of {n} health-claim substances associated with the brand carry an "
                   f"EU-authorised claim (Reg. 1924/2006); the rest are non-authorised"),
        "peers": peers,
        "peers_label": "Associated substances (✓ = EU-authorised)",
    }