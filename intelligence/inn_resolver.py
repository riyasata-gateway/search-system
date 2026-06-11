"""Resolve a brand (trade name) → its active substance(s) / INN, dynamically.

The pharmacovigilance + drug databases (openFDA, EudraVigilance, BCFI) are
indexed by *substance*, not trade name, so we must resolve the molecule to pull
per-brand safety data.

Reality check (probed 2026-06-04): there is no free, live, structured API that
resolves *Belgian/EU* trade names reliably. The authoritative source — the FAGG
**SAM** authentic-source drug master — is login-gated / an Angular SPA with no
open API; its bulk XML export (free, but needs registration + processing) is the
real gold standard. The free live APIs only cover US/internationally-registered
brands:
  • RxNorm (NIH RxNav)  — brand → ingredient
  • openFDA drug/label  — brand_name → generic_name

So this resolver is **dynamic-first, vetted-fallback**: it queries RxNorm then
openFDA live (self-updating, covers any US/intl brand incl. future ones), and
falls back to a small curated map (`core.framework_catalog.BRAND_INN`) for the
EU-only OTC brands the public APIs don't carry (Dafalgan, Nurofen, Fenistil…).
Swap in a SAM-backed resolver here when the bulk dataset is available — the rest
of the pipeline is unchanged.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from typing import Dict, List, Optional

import httpx

from core.logging import get_logger

logger = get_logger(__name__)

# Authoritative Belgian brand → active-substance map, built from the FAGG SAM
# export by scripts/build_sam_inn.py. When present this is the primary source of
# truth (ground truth for the Belgian market) and the live APIs become fallback.
_SAM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sam", "brand_inn.json")

# Substance-level EU↔US synonyms so a SAM/EU INN still hits US-named databases
# (openFDA/FAERS uses "acetaminophen" for "paracetamol", etc.).
_SUBSTANCE_SYNONYMS = {
    "paracetamol": ["paracetamol", "acetaminophen"],
    "adrenaline": ["adrenaline", "epinephrine"],
    "salbutamol": ["salbutamol", "albuterol"],
}


def _load_sam() -> Dict[str, List[str]]:
    try:
        with open(_SAM_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


_SAM_MAP = _load_sam()


# Salt / hydrate suffixes to strip so "Diclofenac Sodium" → "diclofenac" (the base
# INN that pharmacovigilance databases are keyed on).
_SALT_SUFFIXES = [
    "phosphate hemihydrate", "hydrochloride", "diethylamine", "mononitrate",
    "hemihydrate", "phosphate", "carbonate", "sulfate", "sulphate", "citrate",
    "acetate", "maleate", "lysine", "sodium", "besilate", "mesilate", "tartrate",
]
# Excipients / generics that aren't the brand's safety-relevant active molecule.
_DENY = {"caffeine", "ascorbic acid", "sodium ascorbate", "menthol",
         "calcium carbonate", "calcium", "sodium", "glucose", "sucrose"}
_HOMEO = re.compile(r"^\d+\s*(ch|k|dh|x)$")


def is_belgian_medicine(brand: str) -> bool:
    """True if SAM lists this brand as a registered *medicine* (AMP), as opposed
    to a parapharmacy/cosmetic product (NONMEDICINAL registry)."""
    e = _SAM_MAP.get(brand)
    if not e:
        return False
    # New SAM format carries an explicit flag; old format (substances present) implies medicine.
    if "is_medicine" in e:
        return bool(e["is_medicine"])
    return bool(e.get("primary") or e.get("atc"))


def sam_meta(brand: str) -> dict:
    """Full SAM entry for a brand: {primary, all, cnk:[...], atc:[{code,desc}]}."""
    return _SAM_MAP.get(brand) or {}


def _base_inn(s: str) -> str:
    s = s.lower().strip()
    for suf in _SALT_SUFFIXES:
        if s.endswith(" " + suf):
            s = s[: -len(suf) - 1].strip()
    return s


def _normalise(substances: List[str]) -> List[str]:
    """Base-molecule, drop excipients/homeopathic dilutions, expand EU↔US synonyms."""
    out: List[str] = []
    for s in substances:
        b = _base_inn(s)
        if not b or b in _DENY or _HOMEO.match(b):
            continue
        out.extend(_SUBSTANCE_SYNONYMS.get(b, [b]))
    seen, uniq = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


# back-compat alias (live-API paths already return base names)
_expand_synonyms = _normalise

_RXNAV = "https://rxnav.nlm.nih.gov/REST"
_OPENFDA_LABEL = "https://api.fda.gov/drug/label.json"
_BCFI_SEARCH = "https://www.bcfi.be/nl/wp-json/wp/v2/search"
# Dutch words common in BCFI Folia headlines that are NOT substances.
_BCFI_STOP = {
    "geneesmiddelen", "geneesmiddel", "risico", "patiënten", "zwangerschap",
    "borstvoeding", "veilig", "verband", "nieuwigheden", "verandering",
    "belangrijke", "combinatie", "migraine", "welke", "tussen", "causaal",
    "oraal", "bloeding", "doseerpipet", "siroop", "nsaid",
}


def _rxnorm(client: httpx.Client, brand: str) -> Optional[List[str]]:
    r = client.get(f"{_RXNAV}/rxcui.json", params={"name": brand, "search": 2}).json()
    ids = r.get("idGroup", {}).get("rxnormId", [])
    if not ids:
        return None
    rel = client.get(f"{_RXNAV}/rxcui/{ids[0]}/related.json", params={"tty": "IN"}).json()
    for g in rel.get("relatedGroup", {}).get("conceptGroup", []):
        if g.get("tty") == "IN":
            names = [p["name"].lower() for p in g.get("conceptProperties", [])]
            if names:
                return names
    return None


def _rxnorm_is_ingredient(client: httpx.Client, term: str) -> bool:
    """Validate that a candidate word is a real drug ingredient (RxNorm tty=IN)."""
    r = client.get(f"{_RXNAV}/rxcui.json", params={"name": term, "search": 2}).json()
    ids = r.get("idGroup", {}).get("rxnormId", [])
    if not ids:
        return False
    rel = client.get(f"{_RXNAV}/rxcui/{ids[0]}/related.json", params={"tty": "IN"}).json()
    for g in rel.get("relatedGroup", {}).get("conceptGroup", []):
        if g.get("tty") == "IN" and g.get("conceptProperties"):
            return True
    return False


def _bcfi_folia(client: httpx.Client, brand: str) -> Optional[List[str]]:
    """Belgian source: mine BCFI/CBIP Folia headlines for the brand, then keep the
    most-frequent term that RxNorm confirms is an actual ingredient. Covers EU-only
    brands the US APIs miss (e.g. Dafalgan/Perdolan → paracetamol)."""
    d = client.get(_BCFI_SEARCH, params={"search": brand, "per_page": 10}).json()
    text = " ".join((x.get("title") or "") for x in d).lower()
    words = Counter(re.findall(r"[a-zàâéèêïî]{5,}", text))
    for word, _ in words.most_common(12):
        if word in _BCFI_STOP or word.lower() == brand.lower():
            continue
        if _rxnorm_is_ingredient(client, word):
            return [word]
    return None


def _openfda_label(client: httpx.Client, brand: str) -> Optional[List[str]]:
    r = client.get(_OPENFDA_LABEL, params={"search": f'openfda.brand_name:"{brand}"', "limit": 1})
    if r.status_code != 200:
        return None
    res = r.json().get("results", [])
    if not res:
        return None
    gen = res[0].get("openfda", {}).get("generic_name", [])
    return [g.lower() for g in gen] or None


def resolve_inn(brand: str, fallback: Optional[List[str]] = None) -> Optional[List[str]]:
    """Active substance(s) for a trade name.

    SAM (authoritative Belgian drug master) first; then live RxNorm → openFDA →
    BCFI; then the curated fallback. SAM substances are expanded with EU↔US
    synonyms so they still hit US-named databases.
    """
    # 1) SAM — ground truth for the Belgian market. Use the primary (rank-1)
    #    ingredients, normalised to base molecules.
    entry = _SAM_MAP.get(brand)
    if entry:
        primary = entry.get("primary") if isinstance(entry, dict) else entry
        inn = _normalise(primary or [])
        if inn:
            logger.info("inn_resolved", brand=brand, source="sam", inn=inn)
            return inn
    # When SAM is loaded it is AUTHORITATIVE for the Belgian catalogue: a brand
    # absent from SAM is not a registered medicine here (cosmetic/supplement), so
    # we must NOT let the live APIs guess a substance (they return excipients like
    # "glycerin" for cosmetics). Only fall through to live lookups if SAM is
    # unavailable (export not downloaded).
    if _SAM_MAP:
        return None
    try:
        with httpx.Client(timeout=12, headers={"User-Agent": "PharmaWatch/1.0 (pharma research)"}) as c:
            # RxNorm/openFDA cover US/intl brands; BCFI (Belgian) covers EU-only ones.
            for fn in (_rxnorm, _openfda_label, _bcfi_folia):
                try:
                    hit = fn(c, brand)
                except Exception:
                    hit = None
                if hit:
                    logger.info("inn_resolved", brand=brand, source=fn.__name__, inn=hit)
                    return hit
    except Exception as exc:
        logger.warning("inn_resolve_failed", brand=brand, error=str(exc))
    if fallback:
        logger.info("inn_fallback", brand=brand, inn=fallback)
    return fallback
