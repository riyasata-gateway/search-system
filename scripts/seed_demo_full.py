"""Make the *non-search* surfaces of the demo work end-to-end against the
REAL corpus — no fabricated business metrics.

Background: the search system is fully working, but the other tabs (Pharmacist
dashboard, Lab/Brand, Alerts) appeared "dead" because:
  - demo accounts were never linked to a pharmacy / brand,
  - no Alert rows existed (the alert engine had never run over the corpus),
  - no trend signals / recommendations existed,
  - mentions were entity-linked to brands/products but never to *categories*,
    which the pharmacist trend + recommendation engines key off.

This script fixes all of that by DERIVING from real data and running the real
engines. It does NOT invent sales, inventory, or market data (those need
commercial feeds we don't have) — so the supply-chain panels stay honestly
empty. Everything it writes is either account config (which pharmacy/brand a
demo login belongs to) or a deterministic roll-up of mentions that already
exist.

Idempotent — safe to re-run.

Usage:  .venv/bin/python scripts/seed_demo_full.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from core.config import settings
from intelligence.pharmacist_recommender import generate_recommendations
from intelligence.trend_engine import compute_trend_signals
from models.adverse_event import AdverseEventCandidate
from models.alert import Alert, AlertSeverity, AlertType
from models.brand import Brand
from models.mention import (
    EntityType,
    Mention,
    MentionClassification,
    MentionEntity,
    RiskType,
)
from models.pharmacy import Pharmacy
from models.product import Product
from models.trend import TrendPeriod
from models.user import User, UserRole


def _now():
    return datetime.now(timezone.utc)


def link_accounts(db: Session) -> None:
    """Attach demo logins to a pharmacy / brand group so their dashboards load.

    This is account configuration (like seeding the logins themselves), not
    business data. The pharmacy is a real demo location with no fabricated
    sales/inventory.
    """
    # A single demo pharmacy in Belgium (most of the corpus is BE-localised).
    pharmacy = db.execute(
        select(Pharmacy).where(Pharmacy.name == "Pharmacie Demo Bruxelles")
    ).scalar_one_or_none()
    if not pharmacy:
        pharmacy = Pharmacy(
            name="Pharmacie Demo Bruxelles",
            country="BE",
            region="Brussels-Capital",
            city="Brussels",
        )
        db.add(pharmacy)
        db.flush()
        print(f"  + created demo pharmacy id={pharmacy.id} (BE / Brussels)")
    else:
        print(f"  = demo pharmacy already exists id={pharmacy.id}")

    # The brand group the lab personas "own": the group of the most-mentioned brand.
    top_brand_id = db.execute(
        select(MentionEntity.entity_id)
        .where(MentionEntity.entity_type == EntityType.brand)
        .group_by(MentionEntity.entity_id)
        .order_by(func.count().desc())
        .limit(1)
    ).scalar_one_or_none()
    brand_group_id = None
    if top_brand_id:
        brand_group_id = db.execute(
            select(Brand.brand_group_id).where(Brand.id == top_brand_id)
        ).scalar_one_or_none()

    for user in db.execute(select(User)).scalars().all():
        if user.role == UserRole.pharmacist and user.pharmacy_id is None:
            user.pharmacy_id = pharmacy.id
            if pharmacy.owner_user_id is None:
                pharmacy.owner_user_id = user.id
            print(f"  + linked {user.email} → pharmacy {pharmacy.id}")
        if (
            user.role in (UserRole.brand_manager, UserRole.marketing)
            and getattr(user, "brand_group_id", None) is None
            and brand_group_id is not None
        ):
            user.brand_group_id = brand_group_id
            print(f"  + linked {user.email} → brand_group {brand_group_id}")
    db.commit()


def derive_category_links(db: Session) -> int:
    """A mention that names a product also concerns that product's category.

    The pharmacist trend + recommendation engines key off category-level
    signals; the dictionary resolver only emits brand/product. This rolls
    existing product links up to their category — a deterministic projection
    of real links, not new signal.
    """
    product_links = db.execute(
        select(MentionEntity.mention_id, MentionEntity.entity_id, MentionEntity.confidence)
        .where(MentionEntity.entity_type == EntityType.product)
    ).fetchall()

    # product_id -> category_id
    cat_by_product = dict(
        db.execute(select(Product.id, Product.category_id)).fetchall()
    )

    existing_cat = {
        (mid, eid)
        for mid, eid in db.execute(
            select(MentionEntity.mention_id, MentionEntity.entity_id)
            .where(MentionEntity.entity_type == EntityType.category)
        ).fetchall()
    }

    made = 0
    for mention_id, product_id, conf in product_links:
        category_id = cat_by_product.get(product_id)
        if category_id is None:
            continue
        if (mention_id, category_id) in existing_cat:
            continue
        db.add(MentionEntity(
            mention_id=mention_id,
            entity_type=EntityType.category,
            entity_id=category_id,
            confidence=round(float(conf or 1.0), 3),
        ))
        existing_cat.add((mention_id, category_id))
        made += 1
    db.commit()
    return made


def backfill_alerts(db: Session) -> dict:
    """Create the alerts the real-time pipeline would have created, from the
    classifications that already exist. Deterministic & deduplicated by the
    mention/candidate id stored in the payload — re-running adds nothing.
    """
    # Which mention_ids already have an alert (any type)?
    existing_payloads = db.execute(select(Alert.payload)).fetchall()
    seen_mentions = set()
    seen_candidates = set()
    for (payload,) in existing_payloads:
        if not payload:
            continue
        if payload.get("mention_id"):
            seen_mentions.add(payload["mention_id"])
        if payload.get("candidate_id"):
            seen_candidates.add(payload["candidate_id"])

    counts = {"adverse_event": 0, "shortage": 0, "misinformation": 0}

    def _alert_ts(published_at):
        # Use the mention's own date when recent, else detection time (now).
        if published_at is not None:
            ts = published_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts <= _now() and ts >= _now() - timedelta(days=180):
                return ts
        return _now()

    # 1) Adverse-event candidates → critical AE alerts (one per candidate).
    candidates = db.execute(select(AdverseEventCandidate)).scalars().all()
    mention_pub = dict(
        db.execute(select(Mention.id, Mention.published_at)).fetchall()
    )
    for cand in candidates:
        if cand.id in seen_candidates:
            continue
        db.add(Alert(
            alert_type=AlertType.adverse_event,
            severity=AlertSeverity.critical,
            entity_type="mention",
            description=(
                f"Adverse event candidate #{cand.id} requires human "
                f"pharmacovigilance review."
            ),
            payload={"mention_id": cand.mention_id, "candidate_id": cand.id},
            created_at=_alert_ts(mention_pub.get(cand.mention_id)),
        ))
        counts["adverse_event"] += 1

    # 2) Risk-classified mentions → shortage (high) / misinformation (medium).
    risk_rows = db.execute(
        select(MentionClassification.mention_id, MentionClassification.risk_type)
        .where(MentionClassification.risk_type.in_([RiskType.shortage, RiskType.misinformation]))
    ).fetchall()
    for mention_id, risk_type in risk_rows:
        if mention_id in seen_mentions:
            continue
        seen_mentions.add(mention_id)
        if risk_type == RiskType.shortage:
            db.add(Alert(
                alert_type=AlertType.shortage,
                severity=AlertSeverity.high,
                entity_type="mention",
                description="Possible product shortage signalled in a monitored mention.",
                payload={"mention_id": mention_id},
                created_at=_alert_ts(mention_pub.get(mention_id)),
            ))
            counts["shortage"] += 1
        elif risk_type == RiskType.misinformation:
            db.add(Alert(
                alert_type=AlertType.misinformation,
                severity=AlertSeverity.medium,
                entity_type="mention",
                description="Possible health misinformation detected in a monitored mention.",
                payload={"mention_id": mention_id},
                created_at=_alert_ts(mention_pub.get(mention_id)),
            ))
            counts["misinformation"] += 1

    db.commit()
    return counts


def main():
    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        print("1) Linking demo accounts to pharmacy / brand group…")
        link_accounts(db)

        print("2) Deriving category entity links from product links…")
        n = derive_category_links(db)
        print(f"   + {n} category links derived")

        print("3) Computing trend signals (7d / 30d / 90d) from real mentions…")
        for period in (TrendPeriod.days_7, TrendPeriod.days_30, TrendPeriod.days_90):
            saved = compute_trend_signals(db, period)
            print(f"   + {period.value}: {saved} signals")

        print("4) Generating pharmacist recommendations per pharmacy…")
        total_recs = 0
        for ph in db.execute(select(Pharmacy)).scalars().all():
            r = generate_recommendations(db, ph.id)
            total_recs += r
            print(f"   + pharmacy {ph.id}: {r} new recommendations")

        print("5) Backfilling alerts from real risk classifications + AE candidates…")
        counts = backfill_alerts(db)
        print(f"   + alerts created: {counts}")

        # Summary
        print("\n=== Summary (live counts) ===")
        from models.trend import TrendSignal
        from models.recommendation import Recommendation
        print("  alerts:           ", db.execute(select(func.count()).select_from(Alert)).scalar())
        print("  trend_signals:    ", db.execute(select(func.count()).select_from(TrendSignal)).scalar())
        print("  recommendations:  ", db.execute(select(func.count()).select_from(Recommendation)).scalar())
        print("  category links:   ", db.execute(
            select(func.count()).select_from(MentionEntity)
            .where(MentionEntity.entity_type == EntityType.category)
        ).scalar())
        print("Done.")


if __name__ == "__main__":
    main()