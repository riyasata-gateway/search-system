"""Load the EU Register of nutrition & health claims into a local reference file.

The register (Reg. 1924/2006) lists every AUTHORISED and NON-AUTHORISED health
claim, keyed by the nutrient / substance / food the claim is about. Food
supplements (the NUT category) are not medicines — they have no SAM/ATC spine —
so this register is the authoritative way to tell whether a supplement's marketed
benefit is backed by an EU-authorised claim.

Source: the EU Food & Feed Information Portal backend that the official register
UI itself calls. One GET returns the whole register as a nested EAV tree; we
flatten it to one compact row per claim and write `data/eu_health_claims.json`.

Usage:  .venv/bin/python scripts/load_health_claims.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re

import httpx

API = "https://ec.europa.eu/food/food-feed-portal/backend/api/policy-items"
PARAMS = {"foodDomain": "nut", "authorisationType": "nut_auth"}
HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (PharmaWatch)"}

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "eu_health_claims.json")

CLAIM_TYPE = {
    "HCLBT_13_1": "Art 13(1) — general function",
    "HCLBT_13_5": "Art 13(5) — new science / proprietary",
    "HCLBT_14_1_A": "Art 14(1)(a) — disease-risk reduction",
    "HCLBT_14_1_B": "Art 14(1)(b) — children's development",
}
CLAIM_STATUS = {
    "HCCS_AUTHORISED": "authorised",
    "HCCS_NON_AUTHORISED": "non_authorised",
    "HCCS_REVOKED": "revoked",
}


def _flatten(rec: dict) -> dict:
    """Walk the nested {valueIdentifier,value,childrenValues} tree → flat dict."""
    out: dict = {}

    def walk(node):
        vi, v, kids = node.get("valueIdentifier"), node.get("value"), node.get("childrenValues") or []
        if vi and v is not None and not kids:
            out.setdefault(vi, v)
        for c in kids:
            walk(c)

    walk(rec)
    return out


def _strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def main():
    print(f"Fetching EU health-claims register from {API} …")
    resp = httpx.get(API, params=PARAMS, headers=HEADERS, timeout=180)
    resp.raise_for_status()
    raw = resp.json()
    rows = []
    for rec in raw:
        f = _flatten(rec)
        substance = (f.get("hcNutSubFoodCat") or "").strip()
        if not substance:
            continue
        rows.append({
            "substance": substance,
            "claim": _strip_html(f.get("hcClaim")),
            "claim_type": CLAIM_TYPE.get(f.get("hcClaimType"), f.get("hcClaimType")),
            "status": CLAIM_STATUS.get(f.get("hcClaimStatus"), f.get("hcClaimStatus")),
            "conditions": _strip_html(f.get("hcCondOfUse")),
            "health_relationship": _strip_html(f.get("hcHealthRelationship")),
            "efsa": f.get("hcEfsaQuestionNbr"),
            "entry_id": f.get("hcEntryId"),
        })

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)

    from collections import Counter
    by_status = Counter(r["status"] for r in rows)
    n_sub = len({r["substance"].lower() for r in rows})
    print(f"Wrote {len(rows)} claims ({n_sub} distinct substances) → {OUT}")
    print("By status:", dict(by_status))


if __name__ == "__main__":
    main()