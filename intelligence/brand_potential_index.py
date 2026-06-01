"""Brand Potential Index (BPI) — the central output of the TDAH framework.

  BPI = Awareness × Adoption × Sentiment × MarketFit

Each component is normalised into a 0–1 share so the final product is itself
0–1, then surfaced as a 0–100 SCORE. The four components map to specific
data sources we already have:

  • Awareness   — total mention volume vs the brand's competitive set
  • Adoption    — pharmacy sales velocity vs competitive set (proxy if no
                  full GERS/IQVIA wiring; uses pharmacy_sales as available)
  • Sentiment   — share of positive-or-neutral mentions, with negatives
                  weighted by engagement (loud complaints sting more)
  • MarketFit   — share-of-voice in the brand's *category*, capturing
                  category resonance independent of headline volume

The function gracefully degrades: if a component has insufficient data, it
falls back to a neutral 0.5 and the confidence is reduced accordingly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from sqlalchemy import func, select
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

    def to_score(self) -> float:
        """0–1 → 0–100. Geometric mean keeps weak components from masking strong ones."""
        product = max(0.001, self.awareness * self.adoption * self.sentiment * self.market_fit)
        # Geometric mean of the four — same as product^(1/4)
        return clamp_score((product ** 0.25) * 100.0)


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

    def to_bundle(self) -> MetricBundle:
        return MetricBundle(
            name="brand_potential_index",
            metrics=[
                as_score(self.bpi_score, "Brand Potential Index",
                         confidence=self.components.confidence,
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
            },
        )


def _mentions_in_window(
    db: Session,
    entity_type: str,
    entity_ids: List[int],
    since: date,
    country: Optional[str] = None,
) -> dict[int, int]:
    if not entity_ids:
        return {}
    q = (
        select(MentionEntity.entity_id, func.count(Mention.id).label("c"))
        .join(Mention, Mention.id == MentionEntity.mention_id)
        .where(
            MentionEntity.entity_type == entity_type,
            MentionEntity.entity_id.in_(entity_ids),
            Mention.published_at >= since,
            Mention.is_deleted.is_(False),
        )
        .group_by(MentionEntity.entity_id)
    )
    if country:
        q = q.where(Mention.country == country)
    return {int(r.entity_id): int(r.c) for r in db.execute(q).fetchall()}


def _engagement_weighted_sentiment(
    db: Session,
    entity_type: str,
    entity_id: int,
    since: date,
    country: Optional[str],
) -> tuple[float, int]:
    """Returns (sentiment_score_0_1, sample_size).

    Each mention contributes (1 + log(1+engagement)) weight. Positive +1,
    neutral +0.5, negative 0. Final is mean-weighted, clamped 0–1.
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
            Mention.published_at >= since,
            Mention.is_deleted.is_(False),
        )
    )
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


def _proxy_adoption_signals(
    db: Session,
    brand_ids: List[int],
    since: date,
    country: Optional[str],
) -> dict[int, int]:
    """Proxy uptake signal per brand when pharmacy_sales is unavailable.

    Equal-weighted blend of real signals we DO have (confirmed design):
        purchase_intent mentions + review-source mentions (app_store/trustpilot)
        + recommendation mentions (intent OR topic)
    Returned per brand; the caller turns it into a share vs category peers, just
    like Awareness. Documented proxy — never fabricated sales.
    """
    if not brand_ids:
        return {}
    from models.mention import Intent, Topic
    review_sources = ("app_store", "trustpilot")
    q = (
        select(MentionEntity.entity_id, Mention.source_type,
               MentionClassification.intent, MentionClassification.topic)
        .join(Mention, Mention.id == MentionEntity.mention_id)
        .outerjoin(MentionClassification,
                   MentionClassification.mention_id == Mention.id)
        .where(
            MentionEntity.entity_type == "brand",
            MentionEntity.entity_id.in_(brand_ids),
            Mention.published_at >= since,
            Mention.is_deleted.is_(False),
        )
    )
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


def _category_peers(db: Session, brand: Brand) -> List[int]:
    """Brand IDs sharing at least one product category with the target."""
    cat_ids_q = (
        select(Product.category_id)
        .where(Product.brand_id == brand.id, Product.category_id.isnot(None))
        .distinct()
    )
    cat_ids = [int(r[0]) for r in db.execute(cat_ids_q).fetchall() if r[0] is not None]
    if not cat_ids:
        return []
    peers_q = (
        select(Product.brand_id)
        .where(Product.category_id.in_(cat_ids))
        .distinct()
    )
    return [int(r[0]) for r in db.execute(peers_q).fetchall() if r[0] is not None]


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

    # ── Awareness ────────────────────────────────────────────────────────────
    mention_counts = _mentions_in_window(db, "brand", peers, since, country)
    my_mentions = mention_counts.get(brand_id, 0)
    peer_total = sum(mention_counts.values())
    if peer_total:
        awareness = my_mentions / peer_total
    else:
        awareness = 0.5  # no peer data → neutral

    # ── Adoption (pharmacy sales velocity vs peers) ──────────────────────────
    peer_sales = {pid: _sales_velocity(db, pid, since, country) for pid in peers}
    my_sales = peer_sales.get(brand_id, 0)
    sales_total = sum(peer_sales.values())
    adoption_is_proxy = False
    if sales_total:
        adoption = my_sales / sales_total
    else:
        # No pharmacy_sales wired → fall back to the documented proxy uptake
        # signal (purchase intent + reviews + advocacy), shared vs peers.
        proxy = _proxy_adoption_signals(db, peers, since, country)
        proxy_total = sum(proxy.values())
        if proxy_total:
            adoption = proxy.get(brand_id, 0) / proxy_total
            adoption_is_proxy = True
        else:
            adoption = 0.5

    # ── Sentiment ────────────────────────────────────────────────────────────
    sentiment, sentiment_n = _engagement_weighted_sentiment(
        db, "brand", brand_id, since, country
    )

    # ── Market Fit ───────────────────────────────────────────────────────────
    # Share of mentions *within the category* — distinct from raw awareness
    # because awareness can be inflated by off-category buzz.
    if peer_total and len(peers) > 1:
        # Penalise concentration: lone-wolf peers shouldn't auto-win
        market_fit = (my_mentions / peer_total) * (len(peers) / (len(peers) + 1))
        market_fit = min(1.0, market_fit * 2.0)  # scale up so realistic shares aren't crushed
    else:
        market_fit = 0.5

    # ── Confidence ───────────────────────────────────────────────────────────
    # High when we have mentions, sales data, and >1 peer.
    confidence_parts = []
    confidence_parts.append(min(1.0, my_mentions / 30.0))
    confidence_parts.append(min(1.0, sentiment_n / 20.0))
    confidence_parts.append(min(1.0, my_sales / 50.0))
    confidence_parts.append(min(1.0, (len(peers) - 1) / 3.0))
    confidence = sum(confidence_parts) / len(confidence_parts)

    comps = BPIComponents(
        awareness=clamp_score(awareness * 100) / 100,
        adoption=clamp_score(adoption * 100) / 100,
        sentiment=clamp_score(sentiment * 100) / 100,
        market_fit=clamp_score(market_fit * 100) / 100,
        confidence=confidence,
    )

    return BPIResult(
        entity_type="brand",
        entity_id=brand_id,
        entity_name=brand.name,
        country=country,
        bpi_score=round(comps.to_score(), 2),
        components=comps,
        window_days=window_days,
        adoption_is_proxy=adoption_is_proxy,
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
