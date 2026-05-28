"""Key Message Tuning — which messages resonate, which fall flat.

For a brand × country, builds a (topic × sentiment × engagement) resonance
table. A "topic" here is the existing classifier output (efficacy, side_effect,
price, availability, packaging, recommendation, general).

Resonance score per topic is the engagement-weighted positive lift:

  resonance = (positive_engagement − negative_engagement) / total_engagement

Range −1 (loved-to-hate) to +1 (loved). We then split the topics into:

  • winning_messages   — resonance > 0.2, total > min_samples
  • losing_messages    — resonance < −0.2, total > min_samples
  • underexposed       — total < min_samples (worth amplifying if positive,
                         worth ignoring if negative)

This is a deterministic analytic; the LLM-augmented "rewrite this message"
draft is a separate call from the frontend that consumes this output.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.logging import get_logger
from intelligence.output_schema import MetricBundle, as_percent, as_score, clamp_score
from models.brand import Brand
from models.mention import Mention, MentionClassification, MentionEntity, Sentiment, Topic

logger = get_logger(__name__)


@dataclass
class TopicResonance:
    topic: str
    total: int
    positive: int
    neutral: int
    negative: int
    engagement_total: int
    resonance: float          # −1 to +1
    bucket: str               # "winning" | "losing" | "neutral" | "underexposed"


@dataclass
class KeyMessageResult:
    brand_id: int
    brand_name: str
    country: Optional[str]
    window_days: int
    topics: List[TopicResonance] = field(default_factory=list)
    winning: List[str] = field(default_factory=list)
    losing: List[str] = field(default_factory=list)
    underexposed: List[str] = field(default_factory=list)
    sample_size: int = 0

    def to_bundle(self) -> MetricBundle:
        # Headline metric: top winning topic's resonance, projected onto 0–100.
        if self.winning:
            top = next((t for t in self.topics if t.topic == self.winning[0]), None)
            top_score = clamp_score((top.resonance + 1) * 50.0) if top else 50.0
            top_label = f"Top winning: {self.winning[0]}"
        else:
            top_score = 50.0
            top_label = "No standout message yet"
        return MetricBundle(
            name="key_message_tuning",
            metrics=[as_score(top_score, top_label, sample_size=self.sample_size)]
            + [as_percent((t.resonance + 1) * 50, f"{t.topic} resonance",
                          sample_size=t.total) for t in self.topics],
            context={
                "brand_id": self.brand_id,
                "brand_name": self.brand_name,
                "country": self.country,
                "winning": self.winning,
                "losing": self.losing,
                "underexposed": self.underexposed,
            },
        )


def _classify_topic(t: TopicResonance, min_samples: int) -> str:
    if t.total < min_samples:
        return "underexposed"
    if t.resonance >= 0.2:
        return "winning"
    if t.resonance <= -0.2:
        return "losing"
    return "neutral"


def compute_key_messages(
    db: Session,
    brand_id: int,
    country: Optional[str] = None,
    window_days: int = 90,
    min_samples: int = 5,
) -> Optional[KeyMessageResult]:
    brand = db.get(Brand, brand_id)
    if brand is None:
        return None

    since = date.today() - timedelta(days=window_days)
    rows_q = (
        select(
            MentionClassification.topic,
            MentionClassification.sentiment,
            Mention.engagement_count,
        )
        .join(MentionEntity, MentionEntity.mention_id == MentionClassification.mention_id)
        .join(Mention, Mention.id == MentionEntity.mention_id)
        .where(
            MentionEntity.entity_type == "brand",
            MentionEntity.entity_id == brand_id,
            Mention.published_at >= since,
            Mention.is_deleted.is_(False),
            MentionClassification.topic.isnot(None),
        )
    )
    if country:
        rows_q = rows_q.where(Mention.country == country)
    rows = db.execute(rows_q).fetchall()

    by_topic: Dict[str, Dict[str, float]] = {}
    for row in rows:
        topic_value = row.topic.value if hasattr(row.topic, "value") else str(row.topic)
        bucket = by_topic.setdefault(
            topic_value,
            {"total": 0, "pos": 0, "neu": 0, "neg": 0, "pos_eng": 0.0, "neg_eng": 0.0, "all_eng": 0.0},
        )
        bucket["total"] += 1
        eng_weight = 1.0 + math.log1p(max(0, int(row.engagement_count or 0)))
        bucket["all_eng"] += eng_weight
        s = row.sentiment
        if s == Sentiment.positive:
            bucket["pos"] += 1
            bucket["pos_eng"] += eng_weight
        elif s == Sentiment.negative:
            bucket["neg"] += 1
            bucket["neg_eng"] += eng_weight
        else:
            bucket["neu"] += 1

    topics: List[TopicResonance] = []
    for tname, b in by_topic.items():
        if b["all_eng"] <= 0:
            resonance = 0.0
        else:
            resonance = (b["pos_eng"] - b["neg_eng"]) / b["all_eng"]
        tr = TopicResonance(
            topic=tname,
            total=int(b["total"]),
            positive=int(b["pos"]),
            neutral=int(b["neu"]),
            negative=int(b["neg"]),
            engagement_total=int(b["all_eng"]),
            resonance=round(resonance, 3),
            bucket="",
        )
        tr.bucket = _classify_topic(tr, min_samples)
        topics.append(tr)
    topics.sort(key=lambda t: t.resonance, reverse=True)

    winning = [t.topic for t in topics if t.bucket == "winning"]
    losing = [t.topic for t in topics if t.bucket == "losing"]
    underexposed = [t.topic for t in topics if t.bucket == "underexposed"]

    result = KeyMessageResult(
        brand_id=brand_id,
        brand_name=brand.name,
        country=country,
        window_days=window_days,
        topics=topics,
        winning=winning,
        losing=losing,
        underexposed=underexposed,
        sample_size=len(rows),
    )
    logger.info(
        "key_messages_computed",
        brand_id=brand_id,
        country=country,
        winning=winning,
        losing=losing,
    )
    return result
