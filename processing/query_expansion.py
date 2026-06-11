"""
Cross-lingual pharma query expansion.

Maps a user query to its EU-market synonyms — generic INN names, common brand
variants across BE/FR/NL/DE/UK, and the same-language local spellings — so a
search for "paracetamol" also finds Doliprane, Dafalgan, Panadol, ben-u-ron,
"acétaminophène", etc.

The dictionary is intentionally small and curated: it covers the OTC drugs
pharmacists and lab users actually search for. Unknown queries pass through
unchanged.
"""
from __future__ import annotations

import re
from typing import List, Tuple

# (canonical_inn, [variants]) — variants include brand names and translations.
# Lower-case, accent-stripped lookup keys; original casing preserved on output.
_PHARMA_SYNONYMS: List[Tuple[str, List[str]]] = [
    ("paracetamol", [
        "acetaminophen", "acétaminophène",
        "doliprane", "dafalgan", "efferalgan", "panadol",
        "perdolan", "ben-u-ron", "panodil",
    ]),
    ("ibuprofen", [
        "ibuprofène", "ibuprofeen",
        "advil", "nurofen", "brufen", "dolormin", "spidifen",
    ]),
    ("aspirin", [
        "aspirine", "acetylsalicylic acid", "acide acétylsalicylique",
        "aspegic", "aspégic", "aspro", "acetylsalicylzuur",
    ]),
    ("omeprazole", [
        "oméprazole", "omeprazol",
        "losec", "mopral", "prilosec", "antra",
    ]),
    ("amoxicillin", [
        "amoxicilline", "amoxicilina",
        "clamoxyl", "augmentin", "flemoxin",
    ]),
    ("diclofenac", [
        "voltaren", "voltarène", "cataflam",
    ]),
    ("loratadine", [
        "loratadina", "claritin", "clarityn", "claritine",
    ]),
    ("cetirizine", [
        "cétirizine", "zyrtec", "reactine", "alerlisin",
    ]),
    ("metformin", [
        "metformine", "glucophage", "stagid",
    ]),
    ("simvastatin", [
        "simvastatine", "zocor", "lodales",
    ]),
]

def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _norm(s: str) -> str:
    return _strip_accents(s.lower()).strip()


# Reverse index: normalised any-variant → (canonical, all_variants)
_LOOKUP: dict[str, Tuple[str, List[str]]] = {}
for canonical, variants in _PHARMA_SYNONYMS:
    all_terms = [canonical] + variants
    for term in all_terms:
        _LOOKUP[_norm(term)] = (canonical, all_terms)


def expand_query(query: str, max_terms: int = 8) -> List[str]:
    """
    Return a deduped list of pharma synonyms for `query`, with the original
    query first. Returns `[query]` when the query isn't in the dictionary.
    """
    q = query.strip()
    if not q:
        return []

    key = _norm(q)
    hit = _LOOKUP.get(key)

    # Try to find a known term inside multi-word queries
    # (e.g. "ibuprofen side effects" → match "ibuprofen")
    if not hit:
        tokens = re.findall(r"[\w\-]+", key)
        for tok in tokens:
            if tok in _LOOKUP:
                hit = _LOOKUP[tok]
                break

    if not hit:
        return [q]

    _, all_terms = hit
    seen = {_norm(q)}
    out = [q]
    for term in all_terms:
        nk = _norm(term)
        if nk in seen:
            continue
        seen.add(nk)
        out.append(term)
        if len(out) >= max_terms:
            break
    return out


def expansion_summary(query: str) -> dict:
    """Convenience: returns {"original": q, "expanded": [...], "is_expanded": bool}."""
    expanded = expand_query(query)
    return {
        "original": query.strip(),
        "expanded": expanded,
        "is_expanded": len(expanded) > 1,
    }
