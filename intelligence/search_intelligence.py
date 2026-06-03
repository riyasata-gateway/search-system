"""Search → DIA intelligence orchestration.

Ties a free-text search to the two-tier metrics that fill the dashboard:

  • snapshot  — descriptive stats of the result batch (core.search_metrics, pure)
  • framework — corpus-based DIA metrics (BPI, SoV, momentum, lifecycle, launch
                 readiness) for the brand the query RESOLVES to, via the existing
                 intelligence/ modules. Null when the query isn't a known brand.

This is SYNC (the intelligence modules + entity resolver use a sync Session); the
async search endpoints call `build_search_intelligence` in a thread executor.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from core.database import SyncSessionLocal
from core.logging import get_logger
from core.role_lens import ADMIN, BRAND_MANAGER, MARKETING, PHARMACIST, role_label
from core.search_metrics import KpiCard, SearchIntelligence, SearchMetrics, compute_metrics
from intelligence.brand_potential_index import compute_bpi
from intelligence.lifecycle import classify_lifecycle
from intelligence.launch_readiness import compute_launch_readiness
from intelligence.momentum import compute_momentum
from models.brand import Brand
from models.product import Product
from processing.entity_resolution import resolve as resolve_entities

logger = get_logger(__name__)

_BPI_WINDOW = 365   # generous window — the seeded corpus is sparse
_MOM_PERIOD = "90d"


def _resolve_brand(db, query: str, expanded_terms: Optional[List[str]]) -> Optional[Tuple[int, str]]:
    """Resolve a query (+ its expanded brand variants) to a single brand_id.

    Brand hits win directly; otherwise a product hit maps up to its brand.
    """
    texts = [query] + [t for t in (expanded_terms or []) if t]
    product_fallback: Optional[int] = None
    for t in texts:
        for e in resolve_entities(t or ""):
            if e["entity_type"] == "brand":
                b = db.get(Brand, int(e["entity_id"]))
                if b:
                    return b.id, b.name
            elif e["entity_type"] == "product" and product_fallback is None:
                product_fallback = int(e["entity_id"])
    if product_fallback is not None:
        p = db.get(Product, product_fallback)
        if p and p.brand_id:
            b = db.get(Brand, p.brand_id)
            if b:
                return b.id, b.name
    return None


def _safe(fn, label):
    try:
        return fn()
    except Exception as exc:  # one module failing must not kill the rest
        logger.warning("search_intel_module_failed", module=label, error=str(exc))
        return None


def _compute_framework(db, brand_id: int, brand_name: str, role: str) -> dict:
    """Run the framework modules and return {bundles, scalars}. BPI + momentum are
    always computed (cheap, and SoV is derived from BPI awareness); lifecycle and
    launch-readiness are added for the strategic roles."""
    bundles: dict = {}
    scalars: dict = {"brand_id": brand_id, "brand_name": brand_name}

    bpi = _safe(lambda: compute_bpi(db, brand_id, window_days=_BPI_WINDOW), "bpi")
    if bpi:
        bundles["bpi"] = bpi.to_bundle().to_dict()
        c = bpi.components
        scalars.update(
            bpi=bpi.bpi_score,
            bpi_awareness=round(c.awareness, 4),
            bpi_adoption=round(c.adoption, 4),
            bpi_sentiment=round(c.sentiment, 4),
            bpi_market_fit=round(c.market_fit, 4),
            bpi_confidence=round(c.confidence, 4),
            adoption_is_proxy=bpi.adoption_is_proxy,
            # Share of Voice = the brand's share of category mentions = BPI awareness.
            sov_percent=round(c.awareness * 100, 2),
        )

    mom = _safe(lambda: compute_momentum(db, "brand", brand_id, period=_MOM_PERIOD), "momentum")
    if mom:
        bundles["momentum"] = mom.to_bundle().to_dict()
        scalars["momentum_score"] = round(mom.momentum_score, 2)

    if role in (BRAND_MANAGER, ADMIN):
        lc = _safe(lambda: classify_lifecycle(db, "brand", brand_id), "lifecycle")
        if lc:
            bundles["lifecycle"] = lc.to_bundle().to_dict()
            scalars["lifecycle_stage"] = lc.stage.value

    if role == BRAND_MANAGER:
        lr = _safe(lambda: compute_launch_readiness(db, brand_id), "launch_readiness")
        if lr:
            bundles["launch_readiness"] = lr.to_bundle().to_dict()
            scalars["launch_readiness"] = round(lr.score, 2)

    return {"bundles": bundles, "scalars": scalars}


def _bpi_tone(v: float) -> Optional[str]:
    return "good" if v >= 60 else "danger" if v < 35 else "warn"


def _combined_headline(role: str, snapshot: SearchMetrics, scalars: dict) -> List[KpiCard]:
    """Lead with the role's framework KPIs (when resolved), then fill from the
    snapshot headline — capped to keep the row scannable."""
    fw: List[KpiCard] = []
    has = lambda k: scalars.get(k) is not None  # noqa: E731

    if role == BRAND_MANAGER:
        if has("bpi"):
            fw.append(KpiCard(key="bpi", label="Brand Potential Index", value=f"{scalars['bpi']:.0f}",
                              sub="Awareness×Adoption×Sentiment×Fit", tone=_bpi_tone(scalars["bpi"])))
        if has("sov_percent"):
            fw.append(KpiCard(key="sov", label="Share of voice", value=f"{scalars['sov_percent']:.0f}%",
                              sub="of category mentions"))
        if has("momentum_score"):
            fw.append(KpiCard(key="momentum", label="Momentum", value=f"{scalars['momentum_score']:+.0f}",
                              sub="trend acceleration",
                              tone="good" if scalars["momentum_score"] > 0 else "danger" if scalars["momentum_score"] < 0 else None))
        if has("launch_readiness"):
            fw.append(KpiCard(key="launch", label="Launch readiness", value=f"{scalars['launch_readiness']:.0f}",
                              sub="go/monitor/hold"))
    elif role == MARKETING:
        if has("sov_percent"):
            fw.append(KpiCard(key="sov", label="Share of voice", value=f"{scalars['sov_percent']:.0f}%",
                              sub="of category mentions"))
        if has("momentum_score"):
            fw.append(KpiCard(key="momentum", label="Buzz momentum", value=f"{scalars['momentum_score']:+.0f}",
                              sub="trend acceleration",
                              tone="good" if scalars["momentum_score"] > 0 else "danger" if scalars["momentum_score"] < 0 else None))
    elif role == PHARMACIST:
        if has("momentum_score"):
            fw.append(KpiCard(key="momentum", label="Molecule momentum", value=f"{scalars['momentum_score']:+.0f}",
                              sub="trend acceleration",
                              tone="good" if scalars["momentum_score"] > 0 else None))
    else:  # admin
        if has("bpi"):
            fw.append(KpiCard(key="bpi", label="Brand Potential Index", value=f"{scalars['bpi']:.0f}",
                              sub="composite", tone=_bpi_tone(scalars["bpi"])))
        if has("sov_percent"):
            fw.append(KpiCard(key="sov", label="Share of voice", value=f"{scalars['sov_percent']:.0f}%",
                              sub="of category mentions"))
        if has("momentum_score"):
            fw.append(KpiCard(key="momentum", label="Momentum", value=f"{scalars['momentum_score']:+.0f}",
                              sub="trend acceleration"))

    # Fill from snapshot headline, skipping any key already shown, cap at 6.
    seen = {c.key for c in fw}
    for c in snapshot.headline:
        if len(fw) >= 6:
            break
        if c.key not in seen:
            fw.append(c)
    return fw


def build_search_intelligence(
    items: List[dict],
    role: str,
    query: str,
    expanded_terms: Optional[List[str]],
    mode: str,
) -> SearchIntelligence:
    """SYNC orchestration — snapshot (always) + framework (when brand resolves)."""
    snapshot = compute_metrics(items, role)

    framework = None
    brand_id = None
    brand_name = None
    try:
        with SyncSessionLocal() as db:
            resolved = _resolve_brand(db, query, expanded_terms)
            if resolved:
                brand_id, brand_name = resolved
                framework = _compute_framework(db, brand_id, brand_name, role)
    except Exception as exc:
        logger.warning("search_intel_framework_failed", error=str(exc))
        framework = None

    scalars = (framework or {}).get("scalars", {}) if framework else {}
    headline = _combined_headline(role, snapshot, scalars)

    return SearchIntelligence(
        role=role,
        role_label=role_label(role),
        mode=mode,
        brand_resolved=framework is not None,
        brand_id=brand_id,
        brand_name=brand_name,
        headline=headline,
        snapshot=snapshot,
        framework=framework,
    )


def flatten_for_db(si: SearchIntelligence) -> dict:
    """Column kwargs for the search_metrics row (typed scalars + jsonb detail)."""
    s = si.snapshot
    sc = (si.framework or {}).get("scalars", {}) if si.framework else {}
    return {
        "role": si.role,
        "mode": si.mode,
        "brand_resolved": si.brand_resolved,
        "brand_id": si.brand_id,
        "brand_name": si.brand_name,
        # framework scalars
        "bpi": sc.get("bpi"),
        "bpi_awareness": sc.get("bpi_awareness"),
        "bpi_adoption": sc.get("bpi_adoption"),
        "bpi_sentiment": sc.get("bpi_sentiment"),
        "bpi_market_fit": sc.get("bpi_market_fit"),
        "bpi_confidence": sc.get("bpi_confidence"),
        "adoption_is_proxy": sc.get("adoption_is_proxy"),
        "sov_percent": sc.get("sov_percent"),
        "momentum_score": sc.get("momentum_score"),
        "lifecycle_stage": sc.get("lifecycle_stage"),
        "launch_readiness": sc.get("launch_readiness"),
        # snapshot scalars
        "total": s.total,
        "sentiment_index": s.sentiment_index,
        "net_sentiment_label": s.net_sentiment_label,
        "reach_total": s.reach_total,
        "engagement_rate": s.engagement_rate,
        "risk_share": s.risk_share,
        "official_coverage": s.official_coverage,
        "source_diversity": s.source_diversity,
        # detail
        "framework": si.framework,
        "snapshot": s.model_dump(),
        "headline": [c.model_dump() for c in si.headline],
    }
