"""Brand Potential Index (BPI) — the central output of the TDAH framework.

  BPI = mean(Awareness, Adoption, Sentiment, MarketFit)   over measured components

The three *competitive* components are expressed as a brand's **percentile rank
within its peer set**, not as a raw market share. Raw share is the wrong
normalisation for a 0–100 index: in a category with hundreds of tracked brands
every non-leader's share rounds to ~0, so the old geometric mean collapsed to a
constant floor (0.001^0.25·100 ≈ 18) and a 200-review brand scored the same as an
8-mention shell. Percentile rank spreads the field meaningfully — a brand in the
top third of its peers reads ~70, the median ~50 — and is robust to category size.

  • Awareness   — percentile of total mention volume vs the competitive set
  • Adoption    — percentile of uptake (pharmacy sales if wired, else the
                  documented proxy: purchase-intent + reviews + recommendations)
  • Sentiment   — ABSOLUTE engagement-weighted positive share (not a rank);
                  loud complaints sting more
  • MarketFit   — percentile of *positive-voice* volume (mentions weighted by
                  sentiment) vs peers — category resonance, distinct from raw reach

Honesty over fabrication: a component with no real signal (no peers to rank
against, or a genuine zero) is flagged (`no_data` / `sole_brand` / `no_signal`)
and EXCLUDED from the mean rather than dressed up as a neutral 0.5. If nothing is
measurable the result is flagged `insufficient` so the UI shows "Insufficient
data" instead of a fake number.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from typing import List, Optional

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from core.logging import get_logger
from intelligence.output_schema import MetricBundle, as_percent, as_score, clamp_score
from models.brand import Brand
from models.mention import Mention, MentionClassification, MentionEntity, Sentiment
from models.pharmacy import PharmacySale
from models.product import Product

logger = get_logger(__name__)


@dataclass
class BPIComponents:
    awareness: float           # 0–1
    adoption: float            # 0–1
    sentiment: float           # 0–1
    market_fit: float          # 0–1
    confidence: float          # 0–1, reflects data sufficiency


@dataclass
class BPIResult:
    entity_type: str
    entity_id: int
    entity_name: str
    country: Optional[str]
    bpi_score: float
    components: BPIComponents
    window_days: int
    adoption_is_proxy: bool = False
    sample_size: int = 0  # mentions about THIS brand in-window — the honest "do we have data?" signal
    # Per-component honesty flag: "ok" | "no_data" (neutral fallback) |
    # "sole_brand" (no category peers → share is degenerate) | "no_signal" (genuine zero).
    # Keeps the UI from dressing a 0.5 fallback up as a real "Moderate" score.
    component_status: Optional[dict] = None
    # True when no component is measurable → the score is not meaningful and the
    # UI should show "Insufficient data" rather than the number.
    insufficient: bool = False
    # B12 — points the action-acceptance flywheel moved the score by (±, bounded).
    flywheel_delta: float = 0.0

    def to_bundle(self) -> MetricBundle:
        return MetricBundle(
            name="brand_potential_index",
            metrics=[
                as_score(self.bpi_score, "Brand Potential Index",
                         confidence=self.components.confidence,
                         sample_size=self.sample_size,
                         comparison_window=f"last {self.window_days}d"),
                as_percent(self.components.awareness * 100, "Awareness"),
                as_percent(self.components.adoption * 100,
                           "Adoption (proxy)" if self.adoption_is_proxy else "Adoption"),
                as_percent(self.components.sentiment * 100, "Sentiment"),
                as_percent(self.components.market_fit * 100, "Market fit"),
            ],
            context={
                "entity_type": self.entity_type,
                "entity_id": self.entity_id,
                "entity_name": self.entity_name,
                "country": self.country,
                "adoption_is_proxy": self.adoption_is_proxy,
                "component_status": self.component_status or {},
                "insufficient": self.insufficient,
                "flywheel_delta": self.flywheel_delta,
            },
        )


# Review/purchase sources: these drive ADOPTION (a review ≈ a purchase), so they
# are excluded from AWARENESS (reach) to keep the two BPI components disjoint.
_REVIEW_SOURCES = ("farmaline", "medimarket", "app_store")

# B12 — flywheel→BPI. The maximum points the execution-feedback signal can move
# the BPI by (in EITHER direction). Deliberately small: BPI must stay a measure
# of the BRAND's market potential; how diligently the user accepts our actions is
# only a minor nudge, never a driver. Needs a minimum of decisions to apply.
_FLYWHEEL_MAX_ADJ = 5.0
_FLYWHEEL_MIN_DECISIONS = 5
_FLYWHEEL_POSITIVE = ("accepted", "acted_upon")
_FLYWHEEL_NEGATIVE = ("skipped", "dismissed")


def _flywheel_bpi_delta(db: Session, brand_name: str) -> tuple[float, dict]:
    """Bounded BPI nudge from action-acceptance (the flywheel). Returns
    (delta_points, info). delta = MAX·(accept_rate−0.5)·2 over the last 180d, so
    all-accepted → +MAX, half → 0, all-rejected → −MAX. Neutral (0) below the
    minimum-decisions floor or with no action history for the brand."""
    if not brand_name:
        return 0.0, {}
    row = db.execute(text("""
        SELECT sum((decision::text = ANY(:pos))::int) AS pos,
               sum((decision::text = ANY(:neg))::int) AS neg
        FROM action_events
        WHERE context->>'brand_name' = :b
          AND created_at >= now() - interval '180 days'
    """), {"b": brand_name, "pos": list(_FLYWHEEL_POSITIVE),
           "neg": list(_FLYWHEEL_NEGATIVE)}).mappings().first()
    pos = int((row and row["pos"]) or 0)
    neg = int((row and row["neg"]) or 0)
    decided = pos + neg
    if decided < _FLYWHEEL_MIN_DECISIONS:
        return 0.0, {"applied": False, "decisions": decided}
    rate = pos / decided
    delta = round(_FLYWHEEL_MAX_ADJ * (rate - 0.5) * 2, 1)
    return delta, {"applied": delta != 0.0, "acceptance_rate": round(rate, 3),
                   "decisions": decided, "delta": delta}


def _mentions_in_window(
    db: Session,
    entity_type: str,
    entity_ids: List[int],
    since: Optional[date],
    country: Optional[str] = None,
    exclude_sources: Optional[tuple] = None,
) -> dict[int, int]:
    """Mention count per entity. `since=None` means all-time (no lower bound).
    `exclude_sources` drops those source_types (used to make Awareness a *reach*
    signal from non-review sources, disjoint from review-driven Adoption)."""
    if not entity_ids:
        return {}
    q = (
        select(MentionEntity.entity_id, func.count(Mention.id).label("c"))
        .join(Mention, Mention.id == MentionEntity.mention_id)
        .where(
            MentionEntity.entity_type == entity_type,
            MentionEntity.entity_id.in_(entity_ids),
            Mention.is_deleted.is_(False),
        )
        .group_by(MentionEntity.entity_id)
    )
    if since is not None:
        q = q.where(Mention.published_at >= since)
    if country:
        q = q.where(Mention.country == country)
    if exclude_sources:
        q = q.where(Mention.source_type.notin_(exclude_sources))
    return {int(r.entity_id): int(r.c) for r in db.execute(q).fetchall()}


def _engagement_weighted_sentiment(
    db: Session,
    entity_type: str,
    entity_id: int,
    since: Optional[date],
    country: Optional[str],
) -> tuple[float, int]:
    """Returns (sentiment_score_0_1, sample_size).

    Each mention contributes (1 + log(1+engagement)) weight. Positive +1,
    neutral +0.5, negative 0. Final is mean-weighted, clamped 0–1.
    `since=None` means all-time (no lower bound).
    """
    import math
    q = (
        select(
            MentionClassification.sentiment,
            Mention.engagement_count,
        )
        .join(MentionEntity, MentionEntity.mention_id == MentionClassification.mention_id)
        .join(Mention, Mention.id == MentionEntity.mention_id)
        .where(
            MentionEntity.entity_type == entity_type,
            MentionEntity.entity_id == entity_id,
            Mention.is_deleted.is_(False),
        )
    )
    if since is not None:
        q = q.where(Mention.published_at >= since)
    if country:
        q = q.where(Mention.country == country)
    rows = db.execute(q).fetchall()
    if not rows:
        return 0.5, 0
    total_weight = 0.0
    weighted_sum = 0.0
    for row in rows:
        eng = max(0, int(row.engagement_count or 0))
        w = 1.0 + math.log1p(eng)
        s = row.sentiment
        contribution = (
            1.0 if s == Sentiment.positive
            else 0.5 if s == Sentiment.neutral
            else 0.0
        )
        weighted_sum += contribution * w
        total_weight += w
    return weighted_sum / total_weight, len(rows)


def _sales_velocity(
    db: Session,
    brand_id: int,
    since: date,
    country: Optional[str],
) -> int:
    """Total units sold across all products under a brand, in the window."""
    q = (
        select(func.coalesce(func.sum(PharmacySale.quantity), 0))
        .join(Product, Product.id == PharmacySale.product_id)
        .where(
            Product.brand_id == brand_id,
            PharmacySale.sale_date >= since,
        )
    )
    if country:
        from models.pharmacy import Pharmacy
        q = q.join(Pharmacy, Pharmacy.id == PharmacySale.pharmacy_id).where(
            Pharmacy.country == country
        )
    return int(db.execute(q).scalar() or 0)


def _sales_velocity_bulk(
    db: Session,
    brand_ids: List[int],
    since: date,
    country: Optional[str],
) -> dict[int, int]:
    """Units sold per brand across the peer set, in one query (vs N per-brand calls)."""
    if not brand_ids:
        return {}
    q = (
        select(Product.brand_id, func.coalesce(func.sum(PharmacySale.quantity), 0))
        .join(Product, Product.id == PharmacySale.product_id)
        .where(Product.brand_id.in_(brand_ids), PharmacySale.sale_date >= since)
        .group_by(Product.brand_id)
    )
    if country:
        from models.pharmacy import Pharmacy
        q = q.join(Pharmacy, Pharmacy.id == PharmacySale.pharmacy_id).where(
            Pharmacy.country == country
        )
    return {int(bid): int(qty or 0) for bid, qty in db.execute(q).fetchall()}


def _proxy_adoption_signals(
    db: Session,
    brand_ids: List[int],
    since: Optional[date],
    country: Optional[str],
) -> dict[int, int]:
    """Proxy uptake signal per brand when pharmacy_sales is unavailable.

    Equal-weighted blend of real signals we DO have (confirmed design):
        purchase_intent mentions + review-source mentions (app_store/farmaline/medimarket)
        + recommendation mentions (intent OR topic)
    Returned per brand; the caller turns it into a share vs category peers, just
    like Awareness. Documented proxy — never fabricated sales.
    """
    if not brand_ids:
        return {}
    from models.mention import Intent, Topic
    # Belgian pharmacy reviews (farmaline/medimarket) are our primary consumer
    # uptake signal — a review IS a purchase. Include them alongside the generic
    # app-store source so adoption reflects real review volume.
    review_sources = ("app_store", "farmaline", "medimarket")
    q = (
        select(MentionEntity.entity_id, Mention.source_type,
               MentionClassification.intent, MentionClassification.topic)
        .join(Mention, Mention.id == MentionEntity.mention_id)
        .outerjoin(MentionClassification,
                   MentionClassification.mention_id == Mention.id)
        .where(
            MentionEntity.entity_type == "brand",
            MentionEntity.entity_id.in_(brand_ids),
            Mention.is_deleted.is_(False),
        )
    )
    if since is not None:
        q = q.where(Mention.published_at >= since)
    if country:
        q = q.where(Mention.country == country)
    signals: dict[int, int] = {bid: 0 for bid in brand_ids}
    for row in db.execute(q).fetchall():
        bid = int(row.entity_id)
        s = 0
        if row.intent == Intent.purchase_intent:
            s += 1
        if (row.source_type or "").lower() in review_sources:
            s += 1
        if row.intent == Intent.recommendation or row.topic == Topic.recommendation:
            s += 1
        signals[bid] = signals.get(bid, 0) + s
    return signals


def _percentile_rank(value: float, peer_values: List[float]) -> Optional[float]:
    """Brand's standing among its peers as a 0–1 rank (mid-rank for ties).

    Only peers with a positive signal count — a field of mostly-empty brands
    shouldn't make a tiny value look strong. Returns None when there aren't ≥2
    such peers to rank against (caller flags it sole_brand / no_data), and 0.0
    for a genuine zero against a real field (caller flags no_signal).
    """
    pos = [v for v in peer_values if v > 0]
    if value <= 0:
        return 0.0 if len(pos) >= 2 else None
    if len(pos) < 2:
        return None
    below = sum(1 for v in pos if v < value)
    equal = sum(1 for v in pos if v == value)   # includes `value` itself
    # Mid-rank percentile: the field minimum gets a small positive floor (not a
    # harsh 0) and the maximum doesn't claim a perfect 1.0 — so a real but small
    # brand reads "weak", not "no signal".
    return (below + 0.5 * equal) / len(pos)


def _positive_voice_bulk(
    db: Session,
    entity_ids: List[int],
    since: Optional[date],
    country: Optional[str],
) -> dict[int, float]:
    """Sentiment-weighted mention volume per brand (positive 1 · neutral 0.5 ·
    negative 0) — the 'positive voice' a brand commands, for the Market-fit rank.
    One aggregate query over the peer set. `since=None` = all-time."""
    if not entity_ids:
        return {}
    weight = case(
        (MentionClassification.sentiment == Sentiment.positive, 1.0),
        (MentionClassification.sentiment == Sentiment.neutral, 0.5),
        else_=0.0,
    )
    q = (
        select(MentionEntity.entity_id, func.coalesce(func.sum(weight), 0.0))
        .join(Mention, Mention.id == MentionEntity.mention_id)
        .join(MentionClassification, MentionClassification.mention_id == Mention.id)
        .where(
            MentionEntity.entity_type == "brand",
            MentionEntity.entity_id.in_(entity_ids),
            Mention.is_deleted.is_(False),
        )
        .group_by(MentionEntity.entity_id)
    )
    if since is not None:
        q = q.where(Mention.published_at >= since)
    if country:
        q = q.where(Mention.country == country)
    return {int(eid): float(w or 0.0) for eid, w in db.execute(q).fetchall()}


@lru_cache(maxsize=1)
def _atc_index() -> dict:
    """{ATC-level-4 class → set(brand names)} from the SAM map — the real
    'competing molecules' frame for medicines (e.g. M01AB = topical NSAIDs)."""
    import json, os
    idx: dict[str, set] = {}
    path = "data/sam/brand_inn.json"
    if not os.path.exists(path):
        return idx
    try:
        data = json.load(open(path))
    except Exception:
        return idx
    for name, meta in data.items():
        for a in (meta.get("atc") or []):
            code = (a.get("code") if isinstance(a, dict) else a) or ""
            if len(code) >= 5:
                idx.setdefault(code[:5], set()).add(name)
    return idx


def _atc_class_peers(db: Session, brand: Brand) -> List[int]:
    """Brand IDs sharing any of the brand's ATC-4 classes (competing molecules).
    Empty for non-medicines / brands with no ATC."""
    from intelligence.inn_resolver import sam_meta
    meta = sam_meta(brand.name) or {}
    classes = {(a.get("code") or "")[:5] for a in (meta.get("atc") or []) if isinstance(a, dict) and a.get("code")}
    classes.discard("")
    if not classes:
        return []
    idx = _atc_index()
    names = set()
    for c in classes:
        names |= idx.get(c, set())
    if len(names) <= 1:
        return []
    rows = db.execute(select(Brand.id).where(Brand.name.in_(names))).fetchall()
    return [int(r[0]) for r in rows]


def _category_peers(db: Session, brand: Brand) -> List[int]:
    """Brand IDs in the target's competitive set.

    Primary signal is the product catalogue (brands sharing a product
    `category_id`). But only a handful of brands have product rows wired, so when
    that yields no real peer set we fall back to the brand's own `category` label
    (e.g. 'OTC analgesic', 'Dermocosmetics') — brands sharing that label ARE the
    competitive set. Without this, a brand with no products is wrongly treated as
    the sole brand in its category and Awareness/Market-fit collapse to 100/50.
    """
    cat_ids_q = (
        select(Product.category_id)
        .where(Product.brand_id == brand.id, Product.category_id.isnot(None))
        .distinct()
    )
    cat_ids = [int(r[0]) for r in db.execute(cat_ids_q).fetchall() if r[0] is not None]
    if cat_ids:
        peers_q = (
            select(Product.brand_id)
            .where(Product.category_id.in_(cat_ids))
            .distinct()
        )
        peers = [int(r[0]) for r in db.execute(peers_q).fetchall() if r[0] is not None]
        if len(peers) > 1:
            return peers

    # (A1) Medicines: the real "competing molecules" frame is the brands sharing an
    # ATC-4 class (e.g. M01AB topical NSAIDs), from SAM — far better than lumping a
    # drug into the ~1,000-brand primary_category bucket. Empty for non-medicines.
    atc_peers = _atc_class_peers(db, brand)
    if len(atc_peers) > 1:
        return atc_peers

    # Fallback: peers sharing the brand's own category FAMILY (parenthetical
    # sub-types like 'Dermocosmetics (sun)' group with their parent family).
    if getattr(brand, "category", None):
        from core.framework_catalog import category_family
        fam = category_family(brand.category)
        rows = db.execute(select(Brand.id, Brand.category)).fetchall()
        fam_peers = [int(r[0]) for r in rows
                     if r[1] is not None and category_family(r[1]) == fam]
        if len(fam_peers) > 1:
            return fam_peers

    # Final fallback: the imported supplier brands have no fine-grained `category`,
    # but they DO carry a 5-code `primary_category` (NUT/RX/PAC/PEC/OTC). Use the
    # brands in that same primary category that actually have linked data as the
    # competitive set — otherwise a supplier brand is wrongly treated as the sole
    # brand in its space and Awareness/Adoption/Market-fit collapse to 100/neutral.
    # Bounded to has-data brands so the per-peer sales loop stays cheap and the
    # share is meaningful (you only compete for voice with brands that have voice).
    if getattr(brand, "primary_category", None):
        rows = db.execute(
            select(Brand.id).where(
                Brand.primary_category == brand.primary_category,
                Brand.id.in_(
                    select(MentionEntity.entity_id)
                    .where(MentionEntity.entity_type == "brand")
                ),
            )
        ).fetchall()
        return [int(r[0]) for r in rows]
    return []


def compute_bpi(
    db: Session,
    brand_id: int,
    country: Optional[str] = None,
    window_days: int = 90,
) -> Optional[BPIResult]:
    """Compute Brand Potential Index for one brand. Returns None if brand missing."""
    brand = db.get(Brand, brand_id)
    if brand is None:
        return None

    since = date.today() - timedelta(days=window_days)
    peers = _category_peers(db, brand)
    if brand_id not in peers:
        peers.append(brand_id)

    # The corpus is fundamentally a historical pharmacy-review archive with only
    # sporadic recent ingestion, so a 90-day window leaves the share metrics empty
    # or skewed (a brand whose reviews are 2-3 years old looks dead next to one that
    # just got a news hit). The BPI is a standing potential index, not a momentum
    # read, so awareness / adoption / market-fit / sentiment are computed all-time.
    voice_since: Optional[date] = None

    sole_brand = len(peers) <= 1

    # ── Peer signals (one bulk query each), then PERCENTILE RANK vs the field ──
    # `mention_counts` = ALL linked mentions, used for the data-volume gate / sample
    # size / confidence (total activity).
    mention_counts = _mentions_in_window(db, "brand", peers, voice_since, country)
    my_mentions = mention_counts.get(brand_id, 0)
    # (A9) Awareness = REACH from non-review sources (news/social/search/forum),
    # disjoint from review-driven Adoption — so review volume no longer inflates
    # BOTH components. (Reviews are the purchase/adoption proxy, below.)
    awareness_counts = _mentions_in_window(db, "brand", peers, voice_since, country,
                                           exclude_sources=_REVIEW_SOURCES)
    my_awareness = awareness_counts.get(brand_id, 0)
    awareness = _percentile_rank(my_awareness, list(awareness_counts.values()))

    # Adoption: real pharmacy sales if wired, else the documented proxy
    # (purchase-intent + reviews + recommendations). One aggregate query over peers.
    peer_sales = _sales_velocity_bulk(db, peers, since, country)
    sales_total = sum(peer_sales.values())
    if sales_total:
        adoption_values = peer_sales
        adoption_is_proxy = False
    else:
        adoption_values = _proxy_adoption_signals(db, peers, voice_since, country)
        adoption_is_proxy = bool(sum(adoption_values.values()))
    my_adoption_raw = adoption_values.get(brand_id, 0)
    adoption = _percentile_rank(my_adoption_raw, list(adoption_values.values()))

    # Sentiment: ABSOLUTE engagement-weighted positive share (not a rank).
    sentiment, sentiment_n = _engagement_weighted_sentiment(
        db, "brand", brand_id, voice_since, country
    )

    # Market fit: category RESONANCE = positivity SHARE (positive voice ÷ total
    # voice) ranked vs peers — deliberately distinct from adoption, which ranks
    # review VOLUME. Ranking positive *volume* here made market_fit a near-perfect
    # duplicate of adoption (both volume-driven); ranking the positivity *rate*
    # rewards a smaller brand that's loved and penalises a big lukewarm one.
    positive_voice = _positive_voice_bulk(db, peers, voice_since, country)
    total_voice = _mentions_in_window(db, "brand", peers, voice_since, country)
    fit_rates = {pid: positive_voice.get(pid, 0.0) / total_voice[pid]
                 for pid in peers if total_voice.get(pid, 0) > 0}
    my_fit_rate = fit_rates.get(brand_id)
    market_fit = (_percentile_rank(my_fit_rate, list(fit_rates.values()))
                  if my_fit_rate is not None else None)

    # ── Per-component honesty flags ──────────────────────────────────────────
    # A share rank is degenerate for a sole brand, and unrankable when <2 peers
    # carry a signal (rank → None). A genuine zero against a real field is no_signal.
    def _share_status(rank: Optional[float], raw: float) -> str:
        if sole_brand:
            return "sole_brand"
        if rank is None:
            return "no_data"          # <2 peers carry a signal → can't rank
        return "no_signal" if raw <= 0 else "ok"   # genuine zero, not just lowest rank

    awareness_status = _share_status(awareness, my_awareness)
    market_fit_status = _share_status(market_fit, positive_voice.get(brand_id, 0.0) if my_fit_rate is not None else 0.0)
    adoption_status = _share_status(adoption, my_adoption_raw)
    if adoption_status == "ok" and adoption_is_proxy:
        adoption_status = "proxy"
    sentiment_status = "no_data" if sentiment_n == 0 else "ok"

    component_status = {
        "awareness": awareness_status,
        "adoption": adoption_status,
        "sentiment": sentiment_status,
        "market_fit": market_fit_status,
    }

    # ── Score = WEIGHTED mean of the genuinely-measured components ────────────
    # (A3) Explicit, documented weights instead of an implicit equal mean — the
    # framework treats Awareness/Adoption as the demand spine, Sentiment/Market-fit
    # as modifiers. Weights are renormalised over the measured set so unmeasured
    # components (no_data/sole_brand) are excluded, never used as neutral filler.
    MEASURED = {"ok", "proxy"}
    WEIGHTS = {"awareness": 0.30, "adoption": 0.25, "sentiment": 0.25, "market_fit": 0.20}
    comp_vals = {
        "awareness": (awareness or 0.0, awareness_status),
        "adoption": (adoption or 0.0, adoption_status),
        "sentiment": (sentiment, sentiment_status),
        "market_fit": (market_fit or 0.0, market_fit_status),
    }
    measured = {k: v for k, (v, s) in comp_vals.items() if s in MEASURED}
    if measured:
        wtot = sum(WEIGHTS[k] for k in measured)
        bpi_score = round(100.0 * sum(WEIGHTS[k] * v for k, v in measured.items()) / wtot, 2)
    else:
        bpi_score = 0.0

    # (A2) Minimum-data gate: a confident composite needs a real volume of in-frame
    # mentions, not 1–3. Below the floor (or with nothing measurable) the score is
    # not a reading — surface "Insufficient data" rather than a number.
    MIN_BPI_MENTIONS = 10
    insufficient = my_mentions < MIN_BPI_MENTIONS or len(measured) == 0

    # ── B12: flywheel → BPI. Apply the bounded execution-feedback nudge ONLY to a
    # real (sufficient) score — never invent a number for an insufficient brand.
    flywheel_delta, flywheel_info = 0.0, {"applied": False}
    if not insufficient:
        flywheel_delta, flywheel_info = _flywheel_bpi_delta(db, brand.name)
        if flywheel_delta:
            bpi_score = clamp_score(bpi_score + flywheel_delta)
    component_status["flywheel"] = flywheel_info

    # ── Confidence ───────────────────────────────────────────────────────────
    # High when we have mentions, an uptake signal, sentiment volume, and >1 peer.
    confidence_parts = [
        min(1.0, my_mentions / 30.0),
        min(1.0, sentiment_n / 20.0),
        min(1.0, my_adoption_raw / 50.0),
        min(1.0, (len(peers) - 1) / 3.0),
    ]
    confidence = sum(confidence_parts) / len(confidence_parts)

    comps = BPIComponents(
        awareness=clamp_score((awareness or 0.0) * 100) / 100,
        adoption=clamp_score((adoption or 0.0) * 100) / 100,
        sentiment=clamp_score(sentiment * 100) / 100,
        market_fit=clamp_score((market_fit or 0.0) * 100) / 100,
        confidence=confidence,
    )

    return BPIResult(
        entity_type="brand",
        entity_id=brand_id,
        entity_name=brand.name,
        country=country,
        bpi_score=bpi_score,
        components=comps,
        window_days=window_days,
        adoption_is_proxy=adoption_is_proxy,
        sample_size=my_mentions,
        component_status=component_status,
        insufficient=insufficient,
        flywheel_delta=flywheel_delta,
    )


def rank_bpi(
    db: Session,
    country: Optional[str] = None,
    window_days: int = 90,
    limit: int = 20,
) -> List[BPIResult]:
    """Rank brands by BPI — the lab dashboard's headline view."""
    brand_ids = [int(r[0]) for r in db.execute(select(Brand.id)).fetchall()]
    out: List[BPIResult] = []
    for bid in brand_ids:
        res = compute_bpi(db, bid, country=country, window_days=window_days)
        if res:
            out.append(res)
    out.sort(key=lambda r: r.bpi_score, reverse=True)
    logger.info("bpi_ranked", country=country, n=len(out))
    return out[:limit]


def compute_competitive_map(
    db: Session,
    brand_id: int,
    country: Optional[str] = None,
    window_days: int = 90,
    max_peers: int = 9,
) -> Optional[dict]:
    """B11 — Brand Competitive Map. Positions a brand against its competing-set
    peers (ATC molecule peers for medicines, category family otherwise) on two
    axes: market presence (awareness/reach percentile) × perception (sentiment).
    Bubble = mention volume; the target brand is flagged is_self.

    Bounded: peers are ranked by mention volume and only the top `max_peers`
    (plus the target) get a full BPI computation, so the chart stays readable and
    the call stays cheap even in a large category family.
    """
    brand = db.get(Brand, brand_id)
    if brand is None:
        return None
    peer_ids = _category_peers(db, brand)
    if not peer_ids:
        peer_ids = [brand_id]

    # Cheap volume ranking to pick the most-relevant competitors first.
    counts = {
        int(r[0]): int(r[1]) for r in db.execute(text("""
            SELECT me.entity_id, count(*) FROM mention_entities me
            JOIN mentions m ON m.id = me.mention_id
            WHERE me.entity_type = 'brand' AND me.entity_id = ANY(:ids) AND m.is_deleted = false
            GROUP BY me.entity_id
        """), {"ids": peer_ids}).fetchall()
    }
    ranked = sorted(peer_ids, key=lambda p: counts.get(p, 0), reverse=True)
    keep = ranked[:max_peers]
    if brand_id not in keep:
        keep.append(brand_id)

    nodes = []
    for pid in keep:
        r = compute_bpi(db, pid, country=country, window_days=window_days)
        if r is None:
            continue
        b = db.get(Brand, pid)
        nodes.append({
            "id": pid, "name": b.name if b else str(pid),
            "bpi": None if r.insufficient else r.bpi_score,
            "awareness": round(r.components.awareness * 100, 1),
            "adoption": round(r.components.adoption * 100, 1),
            "sentiment": round(r.components.sentiment * 100, 1),
            "market_fit": round(r.components.market_fit * 100, 1),
            "mentions": r.sample_size,
            "is_self": pid == brand_id,
            "insufficient": r.insufficient,
        })
    # Frame label for the UI: how the peer set was derived.
    frame = "ATC molecule peers" if _atc_class_peers(db, brand) and len(_atc_class_peers(db, brand)) > 1 else "category peers"
    return {"brand_id": brand_id, "brand": brand.name, "frame": frame,
            "peer_count": len(peer_ids), "nodes": nodes}


def compute_competitor_moves(
    db: Session,
    brand_id: int,
    country: Optional[str] = None,
    max_peers: int = 12,
) -> Optional[dict]:
    """B10 — competitor-movement detection. Runs the demand-momentum engine across
    a brand's competing-set peers and surfaces those with a real, rising signal —
    a competitor "making a move" (volume/velocity climbing) you'd want to pre-empt.
    Bounded to the top peers by volume."""
    from intelligence.momentum import compute_momentum
    brand = db.get(Brand, brand_id)
    if brand is None:
        return None
    peers = [p for p in _category_peers(db, brand) if p != brand_id]
    counts = {
        int(r[0]): int(r[1]) for r in db.execute(text("""
            SELECT me.entity_id, count(*) FROM mention_entities me
            JOIN mentions m ON m.id = me.mention_id
            WHERE me.entity_type = 'brand' AND me.entity_id = ANY(:ids) AND m.is_deleted = false
            GROUP BY me.entity_id
        """), {"ids": peers}).fetchall()
    } if peers else {}
    ranked = sorted(peers, key=lambda p: counts.get(p, 0), reverse=True)[:max_peers]

    moves = []
    for pid in ranked:
        mo = compute_momentum(db, "brand", pid, country=country)
        if not (mo and mo.has_signal):
            continue
        b = db.get(Brand, pid)
        vel = round(mo.velocity_pct, 1)
        moves.append({
            "name": b.name if b else str(pid),
            "momentum": round(mo.momentum_score, 1),
            "velocity": vel,
            "current": mo.current_count,
            # A "move" = momentum is materially rising, not just present.
            "rising": mo.momentum_score >= 55 and vel > 0,
        })
    moves.sort(key=lambda m: m["momentum"], reverse=True)
    return {"brand_id": brand_id, "brand": brand.name, "moves": moves}
