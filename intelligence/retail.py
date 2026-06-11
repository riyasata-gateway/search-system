"""Belgian pharmacy retail intelligence (Farmaline catalogue), per brand.

Loaded from data/farmaline/brand_retail.json (built by
scripts/ingest_farmaline_catalogue.py). Provides the pack-level retail layer —
price, promo/discount, stock, online rating — that the public regulatory sources
don't, and that dermo/supplement brands depend on. Read live by the KPI layer.
"""
from __future__ import annotations

import json
import os
from typing import Dict

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "farmaline", "brand_retail.json")


def _load() -> Dict[str, dict]:
    try:
        with open(_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


_RETAIL = _load()


def retail_meta(brand: str) -> dict:
    return _RETAIL.get(brand) or {}
