"""Fetch reachable official brand / manufacturer sites → corpus.

For dermo/supplement brands the official catalogue is the main structured source
(claims language, positioning, ingredients) since their regulatory layer is thin.
This fetches each reachable brand site's homepage, extracts the main text, and
stores it as a `brand_site` mention linked to the brand — the brand's own
claims/positioning, searchable and available for claims-vs-evidence analysis.

Only sites confirmed reachable from this host are included; the blocked ones are
listed in BLOCKED for the user (they need a residential proxy or don't resolve).

Usage:  .venv/bin/python scripts/ingest_brand_sites.py
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from ingestion.deduplication import compute_text_hash, is_text_too_short, sanitise_text
from ingestion.connectors.base import RawMention
from models.brand import Brand
from models.mention import EntityType, Mention, MentionEntity

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
      "Accept-Language": "fr-BE,fr;q=0.9,nl;q=0.8,en;q=0.7"}

REACHABLE = {
    "La Roche-Posay": "https://www.laroche-posay.com/",
    "Avène": "https://www.eau-thermale-avene.com/",
    "Vichy": "https://www.vichy.be/",
    "Bioderma": "https://www.bioderma.com/",
    "CeraVe": "https://www.cerave.be/",
    "Eucerin": "https://www.eucerin.be/",
    "Caudalie": "https://be.caudalie.com/",
    "Dafalgan": "https://www.dafalgan.be/",
    "Bion3": "https://www.bion3.fr/",
    "Davitamon": "https://www.davitamon.be/",
    "Solgar": "https://www.solgar.be/",
    "Metagenics": "https://www.metagenics.be/",
    "UCB brands (Keppra, Bimzelx)": "https://www.ucb.com/",
    "Tilman (phyto)": "https://www.tilman.be/",
    "Enterol": "https://www.enterol.be/",
    "Otrivine": "https://www.otrivine.be/",
    "Puressentiel": "https://www.puressentiel.com/",
}


def main():
    import trafilatura
    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        by_name = {b.name: b for b in db.execute(
            select(Brand).where(Brand.category.isnot(None))).scalars().all()}
        linked = set(db.execute(
            select(MentionEntity.entity_id, MentionEntity.mention_id)
            .where(MentionEntity.entity_type == EntityType.brand)).all())

        made = 0
        with httpx.Client(headers=UA, timeout=15, follow_redirects=True, verify=False) as c:
            for brand_name, url in REACHABLE.items():
                brand = by_name.get(brand_name)
                if not brand:
                    continue
                try:
                    resp = c.get(url)
                    text = trafilatura.extract(resp.text, include_comments=False) if resp.status_code == 200 else None
                except Exception as exc:
                    print(f"  {brand_name:30s} ERROR {type(exc).__name__}")
                    continue
                if not text or len(text) < 200:
                    print(f"  {brand_name:30s} no extractable text")
                    continue
                raw = RawMention(source_type="brand_site", source_url=url, country="BE",
                                 language="fr", published_at=datetime.now(timezone.utc),
                                 raw_text=text[:4000], query_used=brand_name,
                                 metadata={"official_site": url})
                th = compute_text_hash(raw)
                m = db.execute(select(Mention).where(Mention.text_hash == th)).scalar_one_or_none()
                if m is None:
                    m = Mention(source_type="brand_site", source_url=url, country="BE", language="fr",
                                published_at=raw.published_at, collected_at=datetime.now(timezone.utc),
                                text_hash=th, raw_text=raw.raw_text, clean_text=sanitise_text(raw.raw_text),
                                query_used=brand_name, raw_metadata={"official_site": url})
                    db.add(m); db.flush()
                if (brand.id, m.id) not in linked:
                    db.add(MentionEntity(mention_id=m.id, entity_type=EntityType.brand,
                                         entity_id=brand.id, confidence=1.0))
                    linked.add((brand.id, m.id)); made += 1
                print(f"  {brand_name:30s} OK ({len(text)} chars)")
        db.commit()
        print(f"\nDone. Linked {made} official brand-site pages.")


if __name__ == "__main__":
    main()
